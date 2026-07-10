import os
import sys
import subprocess

# Ensure reportlab is installed
try:
    import reportlab
except ImportError:
    print("Installing reportlab...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "reportlab"])

from reportlab.lib.pagesizes import A4, landscape
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

class PresentationCanvas(canvas.Canvas):
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
            self.draw_slide_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_slide_decorations(self, page_count):
        self.saveState()
        
        # We are in landscape A4: width = 841.89, height = 595.27
        w, h = 841.89, 595.27
        
        # 1. Background top decorative bar
        self.setFillColor(colors.HexColor("#0F172A")) # Dark Slate
        self.rect(0, h - 12, w, 12, fill=True, stroke=False)
        
        # 2. Primary accent line under top bar
        self.setFillColor(colors.HexColor("#0D9488")) # Medical Teal
        self.rect(0, h - 16, w, 4, fill=True, stroke=False)
        
        # 3. Footer branding
        self.setFont(font_name_bold, 8)
        self.setFillColor(colors.HexColor("#0D9488"))
        self.drawString(40, 25, "Steel Drake Studio Team")
        
        self.setFont(font_name, 8)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawString(160, 25, "|   Проект интеграции ИИ-ассистента Sanarip Med AI и АИС «103»")
        
        # 4. Slide number
        slide_text = f"Слайд {self._pageNumber} из {page_count}"
        self.drawRightString(w - 40, 25, slide_text)
        
        # Footer thin line
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(40, 38, w - 40, 38)
        
        self.restoreState()

def build_pdf(filename="Sanarip_Med_AI_Presentation.pdf"):
    # Setup document in Landscape mode
    w, h = landscape(A4)
    doc = SimpleDocTemplate(
        filename,
        pagesize=(w, h),
        rightMargin=40,
        leftMargin=40,
        topMargin=50,
        bottomMargin=55
    )
    
    c_primary = colors.HexColor("#0D9488")   # Teal
    c_dark = colors.HexColor("#0F172A")      # Dark Slate
    c_slate = colors.HexColor("#334155")     # Slate 700
    c_light_bg = colors.HexColor("#F8FAFC")  # Light Gray
    c_border = colors.HexColor("#E2E8F0")
    
    styles = getSampleStyleSheet()
    
    # Custom Presentation Styles
    style_slide_title = ParagraphStyle(
        'SlideTitle',
        parent=styles['Normal'],
        fontName=font_name_bold,
        fontSize=22,
        leading=26,
        textColor=c_dark,
        spaceAfter=20
    )
    
    style_cover_title = ParagraphStyle(
        'CoverTitle',
        parent=styles['Normal'],
        fontName=font_name_bold,
        fontSize=38,
        leading=44,
        textColor=c_dark,
        spaceAfter=15,
        alignment=1 # Center
    )
    
    style_cover_subtitle = ParagraphStyle(
        'CoverSubtitle',
        parent=styles['Normal'],
        fontName=font_name_italic,
        fontSize=16,
        leading=22,
        textColor=c_primary,
        spaceAfter=40,
        alignment=1 # Center
    )
    
    style_body = ParagraphStyle(
        'SlideBody',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=12,
        leading=18,
        textColor=c_slate,
        spaceAfter=10
    )

    style_body_bold = ParagraphStyle(
        'SlideBodyBold',
        parent=style_body,
        fontName=font_name_bold
    )

    style_bullet = ParagraphStyle(
        'SlideBullet',
        parent=style_body,
        leftIndent=20,
        firstLineIndent=-10,
        spaceAfter=8
    )
    
    style_table_header = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName=font_name_bold,
        fontSize=11,
        leading=14,
        textColor=colors.white
    )
    
    style_table_cell = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=10.5,
        leading=14,
        textColor=c_slate
    )
    
    story = []
    
    # ==================== SLIDE 1: COVER ====================
    story.append(Spacer(1, 80))
    story.append(Paragraph("Sanarip Med AI", style_cover_title))
    story.append(Paragraph("Цифровой ИИ-фронтенд для оптимизации экстренной медицины<br/>и доврачебного триажа в Бишкеке", style_cover_subtitle))
    
    cover_meta = (
        "<font color='#0D9488'><b>Разработчик:</b></font> Steel Drake Studio Team<br/>"
        "<font color='#0F172A'><b>Директор студии / Арт-директор:</b></font> Олег Ермаков<br/>"
        "<font color='#0F172A'><b>Технический Лидер / Куратор:</b></font> Акимхан Солтонкулов"
    )
    story.append(Table([[Paragraph(cover_meta, style_body)]], colWidths=[350], hAlign='CENTER',
                       style=[
                           ('BACKGROUND', (0,0), (-1,-1), c_light_bg),
                           ('BOX', (0,0), (-1,-1), 0.5, c_border),
                           ('PADDING', (0,0), (-1,-1), 12),
                       ]))
    story.append(PageBreak())
    
    # ==================== SLIDE 2 ====================
    story.append(Paragraph("Проблема: Перегрузка «последней мили» медицины", style_slide_title))
    story.append(Paragraph("• <b>Рост населения и расширение Бишкека:</b> Новые жилмассивы увеличивают радиус обслуживания и повышают время прибытия бригад.", style_bullet))
    story.append(Paragraph("• <b>Непрофильные звонки:</b> До 30% обращений на пульт 103 не требуют неотложной помощи (консультации по ОРВИ, легкая температура, беспокойство).", style_bullet))
    story.append(Paragraph("• <b>Трудности с адресом:</b> Поиск точного расположения пациентов в новостройках и плохо освещенных дворах отнимает критически важные минуты.", style_bullet))
    story.append(Paragraph("• <b>Информационный дефицит:</b> Диспетчеры тратят время на долгий опрос взволнованных граждан, пытаясь выявить объективные симптомы.", style_bullet))
    story.append(PageBreak())
    
    # ==================== SLIDE 3 ====================
    story.append(Paragraph("Что такое Sanarip Med AI?", style_slide_title))
    story.append(Paragraph("<b>Sanarip Med AI</b> — это интерактивный сервис в мессенджерах (Telegram/WhatsApp), работающий на базе искусственного интеллекта для первичного контакта с пациентом.", style_body))
    story.append(Paragraph("• <b>Доступность 24/7:</b> Пользователь получает мгновенный отклик ИИ без необходимости ожидания ответа на линии.", style_bullet))
    story.append(Paragraph("• <b>Поддержка трех языков:</b> Общение с пользователем ведется на <b>кыргызском, русском и английском языках</b>.", style_bullet))
    story.append(Paragraph("• <b>Высокая доступность для туристов:</b> Благодаря английскому языку и геолокации, иностранные гости столицы могут легко вызвать помощь, даже не зная города и языков.", style_bullet))
    story.append(Paragraph("• <b>Естественный язык:</b> ИИ распознает как текстовые, так и голосовые сообщения, понимая описание симптомов простыми словами.", style_bullet))
    story.append(PageBreak())
    
    # ==================== SLIDE 4 ====================
    story.append(Paragraph("Постоянный помощник в повседневных случаях", style_slide_title))
    story.append(Paragraph("Сервис полезен в быту ежедневно, даже когда нет угрозы жизни человека:", style_body))
    story.append(Paragraph("• <b>Помощь при мелких травмах:</b> Ситуации вроде «упал, ободрал колено, порезался» не требуют скорой, но вызывают вопросы по обработке.", style_bullet))
    story.append(Paragraph("• <b>Интерактивное руководство:</b> ИИ пошагово объясняет пользователю, как правильно промыть рану, какие антисептики применить и как наложить повязку.", style_bullet))
    story.append(Paragraph("• <b>Снижение паники и самопомощь:</b> Грамотные инструкции помогают человеку быстро оказать самопомощь дома, не перегружая медицинские учреждения.", style_bullet))
    story.append(PageBreak())
    
    # ==================== SLIDE 5 ====================
    story.append(Paragraph("ИИ-зрение: Распознавание травм и экстренных ситуаций по фото", style_slide_title))
    story.append(Paragraph("Пользователь может отправить фотографию поврежденного участка тела для глубокого визуального анализа:", style_body))
    story.append(Paragraph("• <b>Анализ повреждения:</b> ИИ оценивает глубину раны, характер повреждения кожных покровов и уровень угрозы.", style_bullet))
    story.append(Paragraph("• <b>Пример из сценария (укус собаки по пути домой):</b><br/>"
                           "Школьник младших классов получает укус собаки. Он сразу фотографирует рану на телефон. ИИ Sanarip оценивает глубину укуса. Понимая высокую критичность ситуации, ИИ предлагает вызвать 103 и после согласия пользователя в один клик отправляет в диспетчерскую АИС карточку с его точными GPS-координатами, ФИО, симптомами и контактным телефоном для связи.", style_bullet))
    story.append(PageBreak())
    
    # ==================== SLIDE 6 ====================
    story.append(Paragraph("Три сценария помощи при ухудшении самочувствия", style_slide_title))
    story.append(Paragraph("Когда пациент описывает боту плохое самочувствие, Sanarip Med AI предлагает 3 четких варианта действий на выбор:", style_body))
    story.append(Paragraph("1. <b>Вызвать врача на дом поблизости:</b> Бот запрашивает одну кнопку согласия, получает GPS-координаты, ФИО и контактный телефон, после чего оформляет вызов дежурного врача из ближайшего ЦСМ.", style_bullet))
    story.append(Paragraph("2. <b>Записаться к врачу поблизости:</b> Бот находит ближайшую государственную или частную клинику, собирает необходимые данные (GPS, ФИО, телефон) и бронирует запись на прием.", style_bullet))
    story.append(Paragraph("3. <b>Экстренно вызвать 103:</b> ИИ мгновенно формирует карту вызова (GPS, симптомы, ФИО, телефон) и передает её в АИС «103» для отправки реанимационной бригады.", style_bullet))
    story.append(PageBreak())
    
    # ==================== SLIDE 7 ====================
    story.append(Paragraph("В чём отличие от обычного ИИ (Google, ChatGPT)?", style_slide_title))
    story.append(Paragraph("<b>Проблема обычных ИИ-моделей (Google/Gemini/ChatGPT):</b>", style_body_bold))
    story.append(Paragraph("Ищут информацию по всему открытому интернету. В результате авторитетные медицинские данные смешиваются с псевдонаучными блогами и опасными народными советами. Они дают обобщенные ответы и склонны к «галлюцинациям».", style_body))
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>Решение Sanarip Med AI:</b>", style_body_bold))
    story.append(Paragraph("Работа нашего ИИ строго ограничена <b>верифицированной базой данных RAG</b>. Бот строит ответы исключительно на основе сертифицированных клинических протоколов и справочников первой помощи, гарантируя медицинскую безопасность.", style_body))
    story.append(PageBreak())
    
    # ==================== SLIDE 8 ====================
    story.append(Paragraph("Автоматическое обновление данных RAG и источники", style_slide_title))
    story.append(Paragraph("• <b>Актуальность информации:</b> Система RAG-индекса в автоматическом режиме осуществляет парсинг и обновление баз знаний.", style_bullet))
    story.append(Paragraph("• <b>База медицинских специальностей:</b> 59 направлений составлены строго по <b>Официальной Номенклатуре специальностей Минздрава КР</b> с фиксацией зон ответственности (симптомы, заболевания, методы диагностики и показания к приему).", style_bullet))
    story.append(Paragraph("• <b>Клинические протоколы:</b> Синхронизация данных о болезнях с крупнейшим справочником СНГ — <b>MedElement (diseases.medelement.com)</b>.", style_bullet))
    story.append(Paragraph("• <b>Надежность:</b> Информация обновляется автоматически, гарантируя соответствие официальным стандартам без ручного вмешательства.", style_bullet))
    story.append(PageBreak())
    
    # ==================== SLIDE 9 ====================
    story.append(Paragraph("Сравнение концепций: Сила в синергии", style_slide_title))
    
    comparison_data = [
        [Paragraph("<b>АИС «103» (Управление и Логистика)</b>", style_table_header), Paragraph("<b>Sanarip Med AI (Коммуникация и ИИ)</b>", style_table_header)],
        [
            Paragraph("Ориентирована на внутреннюю структуру и работу медиков.", style_table_cell),
            Paragraph("Ориентирована на пациента и его первичное обращение.", style_table_cell)
        ],
        [
            Paragraph("Управляет выездными бригадами, строит маршруты на карте.", style_table_cell),
            Paragraph("Опрашивает пациента, собирает жалобы на трех языках.", style_table_cell)
        ],
        [
            Paragraph("Фиксирует вызов во внутреннем журнале (АРМ диспетчера).", style_table_cell),
            Paragraph("Автоматически определяет GPS-координаты телефона.", style_table_cell)
        ],
        [
            Paragraph("<b>Результат:</b> Отличная база для выполнения вызовов.", style_table_cell),
            Paragraph("<b>Результат:</b> Интеллектуальный входной фильтр для пациентов.", style_table_cell)
        ]
    ]
    
    t_comp = Table(comparison_data, colWidths=[380, 380])
    t_comp.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), c_primary),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, c_border),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, c_light_bg]),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(t_comp)
    story.append(PageBreak())
    
    # ==================== SLIDE 10 ====================
    story.append(Paragraph("Идеальная интеграция: Как мы дополняем АИС «103»", style_slide_title))
    story.append(Paragraph("• <b>Готовый плагин для диспетчерской:</b> Sanarip Med AI не заменяет АИС «103», а расширяет её возможности как готовый внешний ИИ-модуль через API.", style_bullet))
    story.append(Paragraph("• <b>Сквозной процесс:</b> Пациент общается с ботом $\rightarrow$ бот формирует структурированное описание симптомов и точные координаты $\rightarrow$ карточка мгновенно прилетает на пульт АИС «103» диспетчеру.", style_bullet))
    story.append(Paragraph("• <b>Выгода для разработчиков и города:</b> Готовое протестированное решение, не требующее затрат на разработку ИИ-сервисов с нуля.", style_bullet))
    story.append(PageBreak())
    
    # ==================== SLIDE 11 ====================
    story.append(Paragraph("Предложение по пилотному проекту", style_slide_title))
    story.append(Paragraph("• <b>Пилотный запуск в Бишкеке:</b> Тестирование интеграции Sanarip Med AI с АИС «103» на базе одного района города.", style_bullet))
    story.append(Paragraph("• <b>Условия:</b> Полностью безвозмездное предоставление и техническое сопровождение со стороны нашей команды на период пилота (3–6 месяцев).", style_bullet))
    story.append(Paragraph("• <b>Главный фокус сотрудничества:</b> Фильтрация непрофильных/некритических случаев обращений пациентов до того, как они займут ресурсы АИС «103» и выездных бригад.", style_bullet))
    story.append(Spacer(1, 10))
    
    # Team Info Table
    team_data = [
        [Paragraph("<b>Разработчик:</b>", style_table_cell), Paragraph("Steel Drake Studio Team", style_table_cell)],
        [Paragraph("<b>Директор студии / Арт-директор:</b>", style_table_cell), Paragraph("Олег Ермаков", style_table_cell)],
        [Paragraph("<b>Технический Лидер / Куратор:</b>", style_table_cell), Paragraph("Акимхан Солтонкулов", style_table_cell)],
    ]
    t_team = Table(team_data, colWidths=[250, 300])
    t_team.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('LINEBELOW', (0,0), (-1,-1), 0.5, c_border),
    ]))
    story.append(t_team)
    
    doc.build(story, canvasmaker=PresentationCanvas)
    print(f"Presentation PDF successfully built: {filename}")

if __name__ == "__main__":
    build_pdf()
