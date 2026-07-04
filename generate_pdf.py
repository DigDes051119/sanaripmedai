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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# Find and register Cyrillic font
font_path_regular = r"C:\Windows\Fonts\arial.ttf"
font_path_bold = r"C:\Windows\Fonts\arialbd.ttf"
font_path_italic = r"C:\Windows\Fonts\ariali.ttf"

if not os.path.exists(font_path_regular):
    # Fallbacks for Windows/Linux
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
    print("WARNING: Cyrillic font not found. Falling back to Helvetica (Russian letters might not render correctly).")

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
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont(font_name, 9)
        self.setFillColor(colors.HexColor("#4A5568"))
        
        # Header (on pages after cover / page 1)
        if self._pageNumber > 1:
            self.drawString(54, 750, "Sanarip Med AI — Финансовая модель MVP")
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.5)
            self.line(54, 742, 541, 742)
            
        # Footer
        page_text = f"Страница {self._pageNumber} из {page_count}"
        self.drawRightString(541, 40, page_text)
        self.drawString(54, 40, "Конфиденциально")
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(54, 52, 541, 52)
        
        self.restoreState()

def build_pdf(filename="Sanarip_Med_AI_Financial_Model.pdf"):
    # Margins: 0.75 in (54 pt)
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=54,
        leftMargin=54,
        topMargin=110,
        bottomMargin=72
    )
    
    # Custom Palette
    c_primary = colors.HexColor("#0D9488")  # Medical Teal
    c_secondary = colors.HexColor("#0F766E") # Darker Teal
    c_dark = colors.HexColor("#1E293B")      # Dark Slate for text
    c_light = colors.HexColor("#F8FAFC")     # Soft off-white
    c_border = colors.HexColor("#E2E8F0")    # Border Gray
    c_accent = colors.HexColor("#F59E0B")    # Amber Accent
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    style_title = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName=font_name_bold,
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=15
    )
    
    style_subtitle = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName=font_name_italic,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#64748B"),
        spaceAfter=25
    )
    
    style_h1 = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Normal'],
        fontName=font_name_bold,
        fontSize=15,
        leading=18,
        textColor=c_primary,
        spaceBefore=15,
        spaceAfter=10,
        keepWithNext=True
    )
    
    style_h2 = ParagraphStyle(
        'Heading2_Custom',
        parent=styles['Normal'],
        fontName=font_name_bold,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=True
    )
    
    style_body = ParagraphStyle(
        'Body_Custom',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=9.5,
        leading=14,
        textColor=c_dark,
        spaceAfter=8
    )

    style_body_bold = ParagraphStyle(
        'Body_Bold_Custom',
        parent=style_body,
        fontName=font_name_bold
    )
    
    style_callout = ParagraphStyle(
        'Callout',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#1E293B"),
        spaceAfter=10
    )

    style_table_header = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName=font_name_bold,
        fontSize=9.5,
        leading=12,
        textColor=colors.white
    )
    
    style_table_cell = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=9,
        leading=12,
        textColor=c_dark
    )
    
    style_table_cell_bold = ParagraphStyle(
        'TableCellBold',
        parent=styles['Normal'],
        fontName=font_name_bold,
        fontSize=9,
        leading=12,
        textColor=c_dark
    )

    story = []
    
    # --- Header / Title ---
    story.append(Paragraph("Sanarip Med AI", ParagraphStyle('TopBadge', parent=styles['Normal'], fontName=font_name_bold, fontSize=10, leading=12, textColor=c_primary, spaceAfter=5)))
    story.append(Paragraph("Финансовая модель и бюджет MVP", style_title))
    story.append(Paragraph("Расчет расходов на инфраструктуру и потенциального дохода проекта", style_subtitle))
    story.append(Spacer(1, 10))
    
    # --- Section 1: Monetization ---
    story.append(Paragraph("1. Модели монетизации (B2B и B2B2C)", style_h1))
    story.append(Paragraph(
        "Для проекта Sanarip Med AI наиболее эффективна B2B-модель монетизации (работа с клиниками и лабораториями), "
        "так как брать плату за базовую медпомощь с пациентов напрямую снизит доверие и виральность бота. "
        "Ниже представлены основные каналы монетизации и расчет потенциального заработка в месяц:",
        style_body
    ))
    
    # Table of Monetization channels
    monetization_data = [
        [Paragraph("Канал монетизации", style_table_header), Paragraph("Механика и расчет", style_table_header), Paragraph("Доход в месяц (сом)", style_table_header)],
        [
            Paragraph("<b>1. Лидогенерация (CPA)</b>", style_table_cell),
            Paragraph("Комиссия с клиники за запись к врачу (кардиолог, педиатр и др.).<br/><i>Расчет: 15% конверсия в запись от 2250 пользователей = ~330 направлений по 150 сомов за лид.</i>", style_table_cell),
            Paragraph("~49 500 сомов", style_table_cell_bold)
        ],
        [
            Paragraph("<b>2. Подписка (SaaS)</b>", style_table_cell),
            Paragraph("Абонентская плата клиник за приоритетное отображение в списке рекомендаций бота по геолокации.<br/><i>Расчет: подключение 10 партнерских клиник по 3 000 сомов.</i>", style_table_cell),
            Paragraph("30 000 сомов", style_table_cell_bold)
        ],
        [
            Paragraph("<b>3. Анализы (Лаборатории)</b>", style_table_cell),
            Paragraph("Интеграция реферальных промокодов лабораторий (Инвитро, Бонецкого). 10% кэшбэк от заказов.<br/><i>Расчет: 100 заказов в месяц со средним чеком 1500 сомов (150 сомов кэшбэк).</i>", style_table_cell),
            Paragraph("15 000 сомов", style_table_cell_bold)
        ],
        [
            Paragraph("<b>4. Бизнес-подписка (B2B2C)</b>", style_table_cell),
            Paragraph("Продажа бота компаниям как часть соцпакета для сотрудников (первичный ИИ-триаж).<br/><i>Расчет: базовая подписка для компании на 100 сотрудников.</i>", style_table_cell),
            Paragraph("5 000 сомов", style_table_cell_bold)
        ],
        [
            Paragraph("<b>Итоговая выручка на старте</b>", style_table_cell_bold),
            Paragraph("При скромной аудитории в 75 человек в день", style_table_cell),
            Paragraph("~94 500 сомов", style_table_cell_bold)
        ]
    ]
    
    t_mon = Table(monetization_data, colWidths=[1.8*inch, 3.5*inch, 1.5*inch])
    t_mon.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), c_primary),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('TOPPADDING', (0,0), (-1,0), 6),
        ('BACKGROUND', (0,1), (-1,-2), c_light),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#E6F4F1")),
        ('GRID', (0,0), (-1,-1), 0.5, c_border),
        ('BOTTOMPADDING', (0,1), (-1,-1), 6),
        ('TOPPADDING', (0,1), (-1,-1), 6),
    ]))
    story.append(t_mon)
    story.append(Spacer(1, 15))
    
    # --- Section 2: OPEX ---
    story.append(Paragraph("2. Расходы на поддержку (50–100 пользователей в день)", style_h1))
    story.append(Paragraph(
        "Расчет стоимости поддержки проекта при выходе на рабочую мощность (в среднем 75 сессий в день, ~2250 диалогов в месяц):",
        style_body
    ))
    
    # Table of OPEX
    opex_data = [
        [Paragraph("Статья расходов", style_table_header), Paragraph("Детализация и тарифы", style_table_header), Paragraph("Стоимость в месяц (USD / сом)", style_table_header)],
        [
            Paragraph("<b>1. DeepSeek API</b>", style_table_cell),
            Paragraph("Вход: $0.14 / 1M токенов (с кэшем до $0.07). Выход: $0.28 / 1M токенов.<br/><i>Расход: ~12K вх. и ~600 исх. токенов на диалог. В день ~$0.15.</i>", style_table_cell),
            Paragraph("~$4.50<br/>(~400 сомов)", style_table_cell)
        ],
        [
            Paragraph("<b>2. WhatsApp Meta API</b>", style_table_cell),
            Paragraph("Первые 1000 диалогов в месяц — бесплатно. Плата за оставшиеся 1250 диалогов.<br/><i>Тариф для КР (Service/User-initiated): ~$0.015 за диалог.</i>", style_table_cell),
            Paragraph("~$18.75<br/>(~1600 сомов)", style_table_cell)
        ],
        [
            Paragraph("<b>3. Сервер (VPS)</b>", style_table_cell),
            Paragraph("Виртуальный выделенный сервер (например, Host.kg, Hetzner, DigitalOcean) с 2 ГБ RAM для хостинга бота и панели управления.", style_table_cell),
            Paragraph("~$5.00 – $10.00<br/>(~450 – 900 сомов)", style_table_cell)
        ],
        [
            Paragraph("<b>4. Голос и фото (Groq)</b>", style_table_cell),
            Paragraph("Анализ изображений (Llama Vision) и распознавание голосовых сообщений (Whisper). Работает в рамках бесплатных лимитов Groq.", style_table_cell),
            Paragraph("~$0.10<br/>(~10 сомов)", style_table_cell)
        ],
        [
            Paragraph("<b>Итого бюджет поддержки</b>", style_table_cell_bold),
            Paragraph("Вся инфраструктура и каналы связи", style_table_cell),
            Paragraph("~$30.00<br/>(~2 600 сомов)", style_table_cell_bold)
        ]
    ]
    
    t_opex = Table(opex_data, colWidths=[1.8*inch, 3.4*inch, 1.6*inch])
    t_opex.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0F766E")),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('TOPPADDING', (0,0), (-1,0), 6),
        ('BACKGROUND', (0,1), (-1,-2), c_light),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#E6F4F1")),
        ('GRID', (0,0), (-1,-1), 0.5, c_border),
        ('BOTTOMPADDING', (0,1), (-1,-1), 6),
        ('TOPPADDING', (0,1), (-1,-1), 6),
    ]))
    story.append(t_opex)
    story.append(Spacer(1, 15))
    
    # --- Section 3: Financial Summary ---
    story.append(Paragraph("3. Общий финансовый итог в месяц", style_h1))
    
    total_summary_text = (
        "<b>📈 Экономические показатели MVP (в месяц):</b><br/>"
        "• <b>Общая выручка:</b> ~94 500 сомов (при 75 пользователях в день)<br/>"
        "• <b>Бюджет поддержки (OPEX):</b> ~2 600 сомов<br/>"
        "• <b>Чистая прибыль:</b> <b>~91 900 сомов</b> в месяц.<br/><br/>"
        "<font size='8.5' color='#4B5563'><i>Вывод: Проект невероятно экономичен в поддержке благодаря использованию легковесных "
        "баз данных и крайне дешевых API от DeepSeek и Groq. По мере роста аудитории (например, до 500 человек в день) "
        "прибыль будет расти пропорционально, практически не требуя увеличения расходов на инфраструктуру.</i></font>"
    )
    
    t_sum = Table([[Paragraph(total_summary_text, style_callout)]], colWidths=[6.8*inch])
    t_sum.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#FEF3C7")),
        ('BOX', (0,0), (-1,0), 1, c_accent),
        ('TOPPADDING', (0,0), (-1,0), 12),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('LEFTPADDING', (0,0), (-1,0), 14),
        ('RIGHTPADDING', (0,0), (-1,0), 14),
    ]))
    story.append(t_sum)
    
    doc.build(story, canvasmaker=NumberedCanvas)
    print("PDF build successful.")

if __name__ == "__main__":
    build_pdf()
