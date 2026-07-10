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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
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
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont(font_name, 8)
        self.setFillColor(colors.HexColor("#475569"))
        
        # Header (on pages after page 1)
        if self._pageNumber > 1:
            self.drawString(54, 785, "ПУБЛИЧНАЯ ОФЕРТА И ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ — «Sanarip Med AI»")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(54, 777, 541, 777)
            
        # Footer
        page_text = f"Страница {self._pageNumber} из {page_count}"
        self.drawRightString(541, 40, page_text)
        self.drawString(54, 40, "Конфиденциально • Разработано в соответствии с законодательством КР")
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(54, 52, 541, 52)
        
        self.restoreState()

def build_pdf(filename="Sanarip_Med_AI_Public_Offer.pdf"):
    # Margins: 0.75 in (54 pt)
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=54,
        leftMargin=54,
        topMargin=100,
        bottomMargin=72
    )
    
    # Palette
    c_primary = colors.HexColor("#0D9488")   # Teal
    c_dark = colors.HexColor("#1E293B")      # Slate 800
    c_border = colors.HexColor("#E2E8F0")    # Gray 200
    c_light = colors.HexColor("#F8FAFC")     # Soft off-white
    c_warning = colors.HexColor("#991B1B")   # Red for disclaimers
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    style_title = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName=font_name_bold,
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=5,
        alignment=1 # Center
    )
    
    style_subtitle = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName=font_name_italic,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#475569"),
        spaceAfter=15,
        alignment=1 # Center
    )
    
    style_meta = ParagraphStyle(
        'DocMeta',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#64748B"),
        spaceAfter=15
    )
    
    style_h1 = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Normal'],
        fontName=font_name_bold,
        fontSize=11,
        leading=14,
        textColor=c_primary,
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True
    )
    
    style_body = ParagraphStyle(
        'Body_Custom',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=9,
        leading=13.5,
        textColor=c_dark,
        spaceAfter=6
    )

    style_body_bold = ParagraphStyle(
        'Body_Bold_Custom',
        parent=style_body,
        fontName=font_name_bold
    )

    style_body_indent = ParagraphStyle(
        'Body_Indent_Custom',
        parent=style_body,
        leftIndent=15
    )

    style_disclaimer = ParagraphStyle(
        'Disclaimer',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=9,
        leading=13.5,
        textColor=colors.HexColor("#7F1D1D"), # Dark red
        spaceAfter=6
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
        leading=11,
        textColor=c_dark
    )
    
    story = []
    
    # --- Title & Metadata ---
    story.append(Paragraph("ПУБЛИЧНАЯ ОФЕРТА И ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ", style_title))
    story.append(Paragraph("об использовании искусственного интеллекта-помощника «Sanarip Med AI»", style_subtitle))
    
    # Meta (Date and Place)
    meta_table_data = [
        [Paragraph("<b>г. Бишкек</b>", style_meta), Paragraph("<p align='right'><b>Редакция от «09» июля 2026 года</b></p>", style_meta)]
    ]
    t_meta = Table(meta_table_data, colWidths=[3.4*inch, 3.4*inch])
    t_meta.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 10))
    
    # --- Preamble ---
    preamble_text = (
        "Настоящий документ является официальным предложением (публичной офертой) в соответствии со "
        "статьями 396 и 398 Гражданского кодекса Кыргызской Республики. Настоящее Соглашение определяет "
        "условия использования Telegram-бота «Sanarip Med AI» (далее — «Бот» или «Сервис») и регулирует "
        "отношения между Правообладателем (Лицензиаром) и любым физическим лицом, использующим Сервис (далее — «Пользователь»).<br/><br/>"
        "<b>ВНИМАТЕЛЬНО ОЗНАКОМЬТЕСЬ С ТЕКСТОМ НАСТОЯЩЕЙ ОФЕРТЫ. ЕСЛИ ВЫ НЕ СОГЛАСНЫ С ЛЮБЫМ ИЗ ЕЕ ПУНКТОВ, "
        "ВАМ РЕКОМЕНДУЕТСЯ ПРЕКРАТИТЬ ИСПОЛЬЗОВАНИЕ СЕРВИСА.</b>"
    )
    story.append(Paragraph(preamble_text, style_body))
    story.append(Spacer(1, 10))
    
    # --- Section 1: Definitions ---
    story.append(Paragraph("1. ТЕРМИНЫ И ОПРЕДЕЛЕНИЯ", style_h1))
    
    definitions = [
        ("<b>Оферта (Соглашение)</b>", "настоящий документ «Публичная оферта и Пользовательское соглашение», опубликованный Правообладателем в электронной форме и постоянно доступный Пользователю."),
        ("<b>Акцепт</b>", "полное и безоговорочное принятие Пользователем условий настоящей Оферты путем совершения конклюдентных действий: запуска Бота, нажатия кнопки согласия с условиями использования либо начала ведения диалога с Ботом."),
        ("<b>Правообладатель (Лицензиар)</b>", "владелец Сервиса, осуществляющий управление Ботом, администрирование его баз данных и обеспечивающий его техническую работоспособность."),
        ("<b>Пользователь (Лицензиат)</b>", "дееспособное физическое лицо, осуществившее Акцепт Оферты и использующее Сервис в личных некоммерческих ознакомительных целях."),
        ("<b>Сервис (ИИ-помощник / Бот)</b>", "автоматизированная интерактивная программа в мессенджере Telegram («Sanarip Med AI»), функционирующая на основе моделей искусственного интеллекта и предназначенная для предоставления справочно-информационных ответов на вопросы о здоровье.")
    ]
    
    for term, definition in definitions:
        story.append(Paragraph(f"• {term} — {definition}", style_body_indent))
    
    story.append(Spacer(1, 10))
    
    # --- Section 2: Subject ---
    story.append(Paragraph("2. ПРЕДМЕТ СОГЛАШЕНИЯ", style_h1))
    story.append(Paragraph(
        "2.1. Правообладатель предоставляет Пользователю на условиях простой (неисключительной) лицензии право "
        "использования Бота в ознакомительных, информационных и справочных целях на безвозмездной основе.",
        style_body
    ))
    story.append(Paragraph(
        "2.2. Использование Бота допускается исключительно в рамках его функционального назначения, доступного в интерфейсе Telegram.",
        style_body
    ))
    story.append(Paragraph(
        "2.3. Акцептуя данное Соглашение, Пользователь гарантирует, что обладает полной дееспособностью для принятия условий Оферты.",
        style_body
    ))
    
    story.append(Spacer(1, 10))
    
    # --- Section 3: Crucial Disclaimer ---
    story.append(Paragraph("3. МЕДИЦИНСКИЙ ДИСКЛЕЙМЕР И ОГРАНИЧЕНИЕ ОТВЕТСТВЕННОСТИ", style_h1))
    
    disclaimers = [
        "3.1. <b>ИСКЛЮЧИТЕЛЬНО СПРАВОЧНЫЙ ХАРАКТЕР:</b> Бот функционирует автоматически на основе технологий искусственного интеллекта. Ответы Бота носят исключительно справочный, информационный и ознакомительный характер.",
        "3.2. <b>ОТКАЗ ОТ МЕДИЦИНСКОГО СТАТУСА:</b> Бот <b>НЕ является медицинским работником, НЕ оказывает медицинских услуг, НЕ ставит медицинские диагнозы, НЕ назначает лечение, НЕ выписывает рецепты и лекарственные препараты</b>.",
        "3.3. <b>ОБЯЗАТЕЛЬНОСТЬ ВРАЧЕБНОЙ КОНСУЛЬТАЦИИ:</b> Информация, полученная от Бота, ни при каких обстоятельствах <b>не может заменить очную консультацию квалифицированного медицинского специалиста (врача)</b>. Самолечение или отказ от врачебной помощи на основании информации из Бота недопустимы.",
        "3.4. <b>ПОЛНАЯ ОТВЕТСТВЕННОСТЬ ПОЛЬЗОВАТЕЛЯ:</b> Нажимая кнопку согласия и используя Бот, Пользователь соглашается с тем, что берет на себя полную ответственность за любые свои дальнейшие действия, решения, бездействие и выводы, связанные с его здоровьем или здоровьем третьих лиц.",
        "3.5. <b>ОСВОБОЖДЕНИЕ ОТ ОТВЕТСТВЕННОСТИ:</b> Правообладатель, разработчики и партнеры Сервиса ни при каких обстоятельствах не несут ответственности перед Пользователем или третьими лицами за любой ущерб здоровью, моральный вред, убытки или иные негативные последствия, возникшие в результате использования или невозможности использования информации, полученной через Сервис.",
        "3.6. <b>ЭКСТРЕННЫЕ СЛУЧАИ:</b> Бот не предназначен для работы в экстренных ситуациях (острая боль, затрудненное дыхание, потеря сознания, сильное кровотечение и др.). При возникновении симптомов, угрожающих жизни и здоровью, Пользователь обязан немедленно обратиться в государственную службу скорой медицинской помощи (по номеру <b>103</b> на территории Кыргызской Республики) или обратиться в ближайшее медицинское учреждение."
    ]
    
    # Render disclaimer inside a warning callout box
    warning_box_content = []
    for disc in disclaimers:
        warning_box_content.append(Paragraph(disc, style_disclaimer))
    
    t_warning = Table([[warning_box_content]], colWidths=[6.8*inch])
    t_warning.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#FEF2F2")),
        ('BOX', (0,0), (-1,0), 1.2, c_warning),
        ('TOPPADDING', (0,0), (-1,0), 10),
        ('BOTTOMPADDING', (0,0), (-1,0), 10),
        ('LEFTPADDING', (0,0), (-1,0), 12),
        ('RIGHTPADDING', (0,0), (-1,0), 12),
    ]))
    story.append(t_warning)
    story.append(Spacer(1, 10))
    
    # --- Section 4: Rights and Obligations ---
    story.append(Paragraph("4. ПРАВА И ОБЯЗАННОСТИ СТОРОН", style_h1))
    story.append(Paragraph("<b>4.1. Пользователь имеет право:</b>", style_body_bold))
    story.append(Paragraph("• Использовать Бот безвозмездно для личных некоммерческих целей в рамках его функционала.", style_body_indent))
    story.append(Paragraph("• Прекратить использование Бота в любой момент, удалив чат.", style_body_indent))
    
    story.append(Paragraph("<b>4.2. Пользователь обязуется:</b>", style_body_bold))
    story.append(Paragraph("• Предоставлять корректную информацию при формулировании вопросов Боту для получения более релевантных ответов.", style_body_indent))
    story.append(Paragraph("• Не использовать Бот для спама, совершения противоправных действий или попыток дестабилизировать работу программного обеспечения.", style_body_indent))
    story.append(Paragraph("• Не копировать, не модифицировать и не пытаться декомпилировать программный код Бота.", style_body_indent))
    
    story.append(Paragraph("<b>4.3. Правообладатель имеет право:</b>", style_body_bold))
    story.append(Paragraph("• Изменять функционал Бота, вводить новые сервисы или приостанавливать работу Бота для проведения профилактических работ.", style_body_indent))
    story.append(Paragraph("• Заблокировать доступ Пользователю в случае нарушения им условий настоящего Соглашения.", style_body_indent))
    story.append(Paragraph("• Вносить изменения в настоящее Соглашение в одностороннем порядке. Изменения вступают в силу с момента публикации новой редакции.", style_body_indent))
    
    story.append(Spacer(1, 10))
    
    # --- Section 5: Personal Data ---
    story.append(Paragraph("5. ПЕРСОНАЛЬНЫЕ ДАННЫЕ И КОНФИДЕНЦИАЛЬНОСТЬ", style_h1))
    story.append(Paragraph(
        "5.1. В соответствии с Законом Кыргызской Республики «Об информации персонального характера», Пользователь, "
        "осуществляя Акцепт настоящей Оферты, дает свое <b>полное и безусловное согласие на сбор, запись, систематизацию, "
        "накопление, хранение, уточнение (обновление, изменение), извлечение, использование, передачу (включая трансграничную передачу "
        "для обработки ИИ-моделями), обезличивание, блокирование, удаление и уничтожение своих персональных данных</b>.",
        style_body
    ))
    story.append(Paragraph(
        "5.2. Перечень обрабатываемых персональных данных может включать: идентификационный номер пользователя Telegram (Telegram ID), "
        "имя пользователя (username), фамилию и имя (при указании), тексты отправляемых сообщений (включая текстовое описание симптомов), "
        "голосовые сообщения (аудиозаписи голоса), а также загружаемые изображения и фотографии.",
        style_body
    ))
    story.append(Paragraph(
        "5.3. Целью обработки персональных данных является предоставление услуг Бота, обеспечение интерактивной коммуникации с ИИ, "
        "проведение технической диагностики, исправление ошибок и улучшение качества ответов Бота.",
        style_body
    ))
    story.append(Paragraph(
        "5.4. Срок обработки персональных данных длится до момента отзыва согласия Пользователем (путем направления письменного "
        "запроса на электронный адрес Правообладателя) либо до момента прекращения функционирования Сервиса.",
        style_body
    ))
    
    story.append(Spacer(1, 10))
    
    # --- Section 6: Dispute Resolution ---
    story.append(KeepTogether([
        Paragraph("6. РАЗРЕШЕНИЕ СПОРОВ И ПРИМЕНИМОЕ ПРАВО", style_h1),
        Paragraph(
            "6.1. Настоящее Соглашение регулируется и толкуется в соответствии с законодательством Кыргызской Республики.",
            style_body
        ),
        Paragraph(
            "6.2. Все споры и разногласия, возникающие в связи с исполнением настоящего Соглашения, стороны стремятся разрешить путем переговоров. "
            "Срок рассмотрения письменной претензии составляет 30 (тридцать) календарных дней с момента ее получения.",
            style_body
        ),
        Paragraph(
            "6.3. При невозможности достижения согласия спор подлежит рассмотрению в компетентном суде Кыргызской Республики по месту нахождения Правообладателя.",
            style_body
        )
    ]))
    
    story.append(Spacer(1, 10))
    
    # --- Section 7: Requisites ---
    requisites_content = (
        "<b>Адрес для направления претензий:</b> legal@sanaripmed.ai<br/>"
        "<b>Правообладатель:</b> ОсОО «Санарип Мед» (или Индивидуальный Предприниматель)<br/>"
        "<b>Юридический адрес:</b> Кыргызская Республика, г. Бишкек<br/>"
        "<b>ИНН:</b> [Укажите ИНН юридического лица / ИП]<br/>"
        "<b>Электронная почта:</b> info@sanaripmed.ai"
    )
    
    story.append(KeepTogether([
        Paragraph("7. РЕКВИЗИТЫ ПРАВООБЛАДАТЕЛЯ", style_h1),
        Table([[Paragraph(requisites_content, style_body)]], colWidths=[6.8*inch],
              style=[
                  ('BACKGROUND', (0,0), (-1,-1), c_light),
                  ('BOX', (0,0), (-1,-1), 0.5, c_border),
                  ('TOPPADDING', (0,0), (-1,-1), 8),
                  ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                  ('LEFTPADDING', (0,0), (-1,-1), 10),
                  ('RIGHTPADDING', (0,0), (-1,-1), 10),
              ])
    ]))
    
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"PDF successfully generated: {filename}")

if __name__ == "__main__":
    build_pdf()
