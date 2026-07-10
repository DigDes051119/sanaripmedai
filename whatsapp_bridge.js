const { 
    default: makeWASocket, 
    useMultiFileAuthState, 
    DisconnectReason 
} = require('@whiskeysockets/baileys');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
const path = require('path');
const fs = require('fs');

const FLASK_URL = 'http://127.0.0.1:5000/webhook/whatsapp/local';

async function startWhatsAppBridge() {
    console.log('[WhatsApp] Запуск моста Baileys...');
    
    // Папка для хранения авторизационной сессии
    const authFolder = path.join(__dirname, 'data', 'whatsapp_auth_session');
    fs.mkdirSync(authFolder, { recursive: true });
    
    const { state, saveCreds } = await useMultiFileAuthState(authFolder);
    
    const sock = makeWASocket({
        auth: state,
        printQRInTerminal: false // Отключаем стандартный вывод, выведем красиво через qrcode-terminal
    });
    
    // Слушаем статус подключения и QR-код
    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;
        
        if (qr) {
            console.log('\n======================================================');
            console.log('[WhatsApp] Отсканируйте этот QR-код вашим WhatsApp:');
            console.log('======================================================\n');
            qrcode.generate(qr, { small: true });
        }
        
        if (connection === 'close') {
            const shouldReconnect = lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;
            console.log('[WhatsApp] Соединение закрыто из-за: ', lastDisconnect?.error, ', перезапуск: ', shouldReconnect);
            if (shouldReconnect) {
                startWhatsAppBridge();
            }
        } else if (connection === 'open') {
            console.log('\n======================================================');
            console.log('[WhatsApp] Мост успешно подключен и готов к работе!');
            console.log('======================================================\n');
        }
    });
    
    // Сохраняем учетные данные при обновлении
    sock.ev.on('creds.update', saveCreds);
    
    // Обработка входящих сообщений
    sock.ev.on('messages.upsert', async (m) => {
        if (m.type !== 'notify') return;
        
        for (const msg of m.messages) {
            // Игнорируем собственные сообщения и сообщения из групп
            if (msg.key.fromMe) continue;
            const from = msg.key.remoteJid;
            if (!from.endsWith('@s.whatsapp.net')) continue; // Только личные чаты
            
            // Получаем текст сообщения
            const text = msg.message?.conversation || 
                         msg.message?.extendedTextMessage?.text || 
                         msg.message?.imageMessage?.caption || '';
                         
            if (!text) continue;
            
            const senderName = msg.pushName || 'Пользователь WhatsApp';
            const phone = from.split('@')[0];
            
            console.log(`[WhatsApp] Входящее от +${phone} (${senderName}): ${text}`);
            
            try {
                // Пересылаем сообщение во Flask бэкенд
                const response = await axios.post(FLASK_URL, {
                    phone: phone,
                    name: senderName,
                    text: text
                }, { timeout: 20000 });
                
                const replyText = response.data?.text;
                if (replyText) {
                    console.log(`[WhatsApp] Отправляем ответ +${phone}: ${replyText}`);
                    await sock.sendMessage(from, { text: replyText });
                }
            } catch (err) {
                console.error('[WhatsApp] Ошибка отправки на Flask бэкенд или отправки сообщения: ', err.message);
                await sock.sendMessage(from, { 
                    text: 'Извините, произошла техническая ошибка на стороне сервера ИИ-ассистента. Пожалуйста, попробуйте написать позже. 🩺' 
                });
            }
        }
    });
}

// Запуск моста
startWhatsAppBridge().catch(err => {
    console.error('[WhatsApp] Критическая ошибка при запуске моста: ', err);
});
