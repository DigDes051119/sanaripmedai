import os
import sys
import subprocess

# Ensure reportlab is installed
try:
    import reportlab
except ImportError:
    print("Installing reportlab...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "reportlab"])

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# Find and register Cyrillic font
font_path_regular = r"C:\Windows\Fonts\arial.ttf"
font_path_bold = r"C:\Windows\Fonts\arialbd.ttf"
font_path_italic = r"C:\Windows\Fonts\ariali.ttf"

if not os.path.exists(font_path_regular):
    font_path_regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font_path_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_path_italic = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"

if os.path.exists(font_path_regular):
    pdfmetrics.registerFont(TTFont('Arial', font_path_regular))
    pdfmetrics.registerFont(TTFont('Arial-Bold', font_path_bold if os.path.exists(font_path_bold) else font_path_regular))
    pdfmetrics.registerFont(TTFont('Arial-Italic', font_path_italic if os.path.exists(font_path_italic) else font_path_regular))
    font_name = 'Arial'
    font_name_bold = 'Arial-Bold'
    font_name_italic = 'Arial-Italic'
else:
    font_name = 'Helvetica'
    font_name_bold = 'Helvetica-Bold'
    font_name_italic = 'Helvetica-Oblique'
    print("WARNING: Cyrillic font not found. Falling back to Helvetica.")

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont(font_name, 8)
        self.setFillColor(colors.HexColor("#475569"))
        
        # Header (on pages after page 1)
        if self._pageNumber > 1:
            self.drawString(54, 785, "GMKtec EVO-X2: Обзор характеристик и возможностей локального ИИ")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(54, 777, 541, 777)
            
        # Footer
        page_text = f"Страница {self._pageNumber} из {page_count}"
        self.drawRightString(541, 40, page_text)
        self.drawString(54, 40, "Рабочая станция локального ИИ — GMKtec EVO-X2")
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(54, 52, 541, 52)
        
        self.restoreState()

def build_pdf(image_path, output_filename="GMKtec_EVO-X2_Review.pdf"):
    # Margins: 0.75 in (54 pt)
    doc = SimpleDocTemplate(
        output_filename,
        pagesize=A4,
        rightMargin=54,
        leftMargin=54,
        topMargin=80,
        bottomMargin=72
    )
    
    # Palette
    c_primary = colors.HexColor("#4F46E5")   # Indigo
    c_secondary = colors.HexColor("#06B6D4") # Cyan
    c_dark = colors.HexColor("#0F172A")      # Slate 900
    c_text = colors.HexColor("#334155")      # Slate 700
    c_border = colors.HexColor("#E2E8F0")    # Gray 200
    c_light = colors.HexColor("#F8FAFC")     # Soft off-white
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    style_title = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName=font_name_bold,
        fontSize=22,
        leading=26,
        textColor=c_primary,
        spaceAfter=6,
        alignment=0
    )
    
    style_subtitle = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=12,
        leading=16,
        textColor=c_secondary,
        spaceAfter=20,
        alignment=0
    )
    
    style_h1 = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Normal'],
        fontName=font_name_bold,
        fontSize=13,
        leading=16,
        textColor=c_primary,
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True
    )
    
    style_body = ParagraphStyle(
        'Body_Custom',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=9.5,
        leading=14,
        textColor=c_text,
        spaceAfter=6
    )

    style_body_bold = ParagraphStyle(
        'Body_Bold_Custom',
        parent=style_body,
        fontName=font_name_bold
    )

    style_table_header = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName=font_name_bold,
        fontSize=9,
        leading=12,
        textColor=colors.white
    )
    
    style_table_cell = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=8.5,
        leading=11.5,
        textColor=c_dark
    )
    
    style_table_cell_bold = ParagraphStyle(
        'TableCellBold',
        parent=styles['Normal'],
        fontName=font_name_bold,
        fontSize=8.5,
        leading=11.5,
        textColor=c_dark
    )
    
    story = []
    
    # Title & Subtitle
    story.append(Paragraph("Рабочая станция GMKtec EVO-X2", style_title))
    story.append(Paragraph("Полный разбор характеристик, возможностей и требований для локального ИИ", style_subtitle))
    story.append(Spacer(1, 10))
    
    # Top Section with Image and Specs Table
    # Image sizing: let's scale to width of ~180pt, keeping aspect ratio (1:1 approx)
    img_element = None
    if os.path.exists(image_path):
        img_element = Image(image_path, width=180, height=180)
    
    # Specs table data
    specs_data = [
        [Paragraph("Параметр", style_table_header), Paragraph("Характеристика", style_table_header)],
        [Paragraph("Процессор (CPU)", style_table_cell_bold), Paragraph("AMD Ryzen™ AI Max+ 395 (16 ядер / 32 потока, до 5.1 ГГц, Zen 5)", style_table_cell)],
        [Paragraph("Графика (GPU)", style_table_cell_bold), Paragraph("Radeon 8060S (40 ядер RDNA 3.5, мощный встроенный ИИ-ускоритель)", style_table_cell)],
        [Paragraph("Оперативная память", style_table_cell_bold), Paragraph("128 ГБ объединенной памяти LPDDR5X 8000 МГц (распаяна на плате)", style_table_cell)],
        [Paragraph("Накопитель (ROM)", style_table_cell_bold), Paragraph("2 ТБ / 4 ТБ NVMe PCIe 4.0 SSD (возможность расширения до 16 ТБ через M.2)", style_table_cell)],
        [Paragraph("Нейропроцессор (NPU)", style_table_cell_bold), Paragraph("AMD XDNA 2 (50 TOPS). Суммарная мощность чипа до 126 TOPS", style_table_cell)],
        [Paragraph("Сеть и интерфейсы", style_table_cell_bold), Paragraph("2.5G Ethernet, Wi-Fi 7, Bluetooth 5.4, 2 × USB4 (40 Гбит/с), HDMI 2.1, DP 1.4", style_table_cell)],
        [Paragraph("Стоимость", style_table_cell_bold), Paragraph("Официальная цена от $1999 (за максимальную версию 128 ГБ)", style_table_cell)],
    ]
    
    # We lay out the image and table side-by-side or stacked
    # Side-by-side is cleaner using a parent table
    t_specs = Table(specs_data, colWidths=[110, 190])
    t_specs.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), c_primary),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, c_border),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, c_light]),
    ]))
    
    if img_element:
        # Wrap in side-by-side table
        layout_data = [[img_element, t_specs]]
        t_layout = Table(layout_data, colWidths=[190, 310])
        t_layout.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (0,0), (0,0), 'CENTER'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
        ]))
        story.append(t_layout)
    else:
        story.append(t_specs)
        
    story.append(Spacer(1, 15))
    
    # Energy
    story.append(Paragraph("Энергопотребление системы", style_h1))
    energy_text = (
        "Устройство демонстрирует высокую энергоэффективность по сравнению с десктопными ПК с дискретными видеокартами:<br/>"
        "• <b>Режим простоя / веб-серфинг:</b> 15 – 25 Вт.<br/>"
        "• <b>При ИИ-нагрузке (инференс LLM):</b> Стабильная работа на уровне 120 Вт.<br/>"
        "• <b>Пиковые моменты (Boost-режим):</b> Кратковременные скачки до 140 Вт.<br/>"
        "• В комплекте поставляется внешний блок питания мощностью ~230 Вт."
    )
    story.append(Paragraph(energy_text, style_body))
    
    # Speed & Inference
    story.append(Paragraph("Производительность и скорость в задачах ИИ", style_h1))
    speed_text = (
        "Благодаря огромной пропускной способности памяти LPDDR5X (8000 МГц), мини-ПК выдает отличную скорость генерации токенов на локальных ИИ-моделях:<br/>"
        "• <b>Модели до 32 млрд параметров (32B):</b> Скорость составляет около <b>25–40 токенов в секунду</b> (быстрее, чем читает человек).<br/>"
        "• <b>Тяжелые модели (70B–90B):</b> Скорость генерации держится на уровне <b>10–15 токенов в секунду</b>.<br/>"
        "В экосистеме софта (LM Studio, Ollama) устройство показывает производительность в инференсе, оптимизированную под длительные нагрузки без перегрева благодаря системе охлаждения с тремя тепловыми трубками."
    )
    story.append(Paragraph(speed_text, style_body))
    
    # Models compatibility
    story.append(Paragraph("Какие модели поместятся в 128 ГБ памяти?", style_h1))
    models_text = (
        "Главное правило локального запуска: веса модели должны полностью помещаться в оперативной памяти. "
        "Объем 128 ГБ позволяет запускать практически любые современные открытые модели вплоть до 70B–90B без потери качества, а также MoE-модели средних размеров. "
        "В BIOS устройства под нужды видеопамяти (VRAM) можно выделить до 96 ГБ ОЗУ.<br/><br/>"
        "<b>Рекомендуемые модели для запуска на GMKtec EVO-X2:</b><br/>"
        "1. <b>Семейство Google Gemma 4:</b><br/>"
        "   - <i>Gemma 4 12B и 26B A4B</i> (включая продвинутые мультимодальные версии с поддержкой картинок и звука) — работают на максимальной скорости в 8-битном или оригинальном качестве.<br/>"
        "   - <i>Gemma 4 31B</i> — флагманская локальная модель от Google с глубоким логическим мышлением (Thinking Mode), отлично работает в квантовании Q4/Q5.<br/>"
        "2. <b>Llama 3.1 / 3.3 (70B):</b> Эталонные модели от Meta для сложных задач, кодинга и аналитики текста. В квантовании Q4_K_M занимают около 43 ГБ ОЗУ, оставляя огромный запас под контекст.<br/>"
        "3. <b>Qwen 2.5 / 2.5-Turbo (72B):</b> Мощнейшая китайская модель, которая в сжатии INT4/INT8 работает без задержек.<br/>"
        "4. <b>Mistral Large 2 (123B):</b> В жестком квантовании (Q3) её также можно запустить на этой системе.<br/><br/>"
        "Устройство полностью заменяет платные облачные подписки на ChatGPT Plus или Claude Pro, позволяя развернуть полноценного ИИ-ассистента (например, локальный аналог Claude Code) прямо у себя дома."
    )
    story.append(Paragraph(models_text, style_body))
    
    doc.build(story, canvasmaker=NumberedCanvas)

if __name__ == "__main__":
    img_path = r"C:\Users\Akimkhan\.gemini\antigravity-ide\brain\c9b0bd3c-ca62-4cab-8865-7b4cb70dd9d6\media__1783612659315.png"
    build_pdf(img_path)
    print("PDF successfully generated!")
