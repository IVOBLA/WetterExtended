// sendMail.js
// Aufruf: node sendMail.js '<JSON-String>'
// Benötigt: Umgebungsvariable SMTP_PASSWORD (GitHub Repository Secret)

'use strict';

const nodemailer = require('nodemailer');

// Sicherheitscheck: SMTP_PASSWORD muss als GitHub Secret gesetzt sein
if (!process.env.SMTP_PASSWORD) {
  console.error('FEHLER: Umgebungsvariable SMTP_PASSWORD nicht gesetzt.');
  console.error('Bitte unter GitHub → Settings → Secrets → SMTP_PASSWORD anlegen.');
  process.exit(1);
}

// Analyse-Daten aus Kommandozeilen-Argument lesen
const rawArg = process.argv[2] || '{}';
let analysis;

try {
  analysis = JSON.parse(rawArg);
} catch (parseError) {
  console.error('FEHLER: Ungültiges JSON als Argument übergeben:', parseError.message);
  analysis = { zusammenfassung: rawArg };
}

// KASSERVER SMTP-Transporter
const transporter = nodemailer.createTransport({
  host: 'w00eab71.kasserver.com',
  port: 587,
  secure: false,
  auth: {
    user: 'claude@blatec.at',
    pass: process.env.SMTP_PASSWORD
  },
  tls: {
    rejectUnauthorized: false
  }
});

// HTML-Mail aufbauen
function buildHtml(data) {
  const zeit = new Date().toLocaleString('de-AT');

  const section = (titel, farbe, hintergrund, items) => {
    if (!items || items.length === 0) return '';
    return `
      <h3 style="color:${farbe}; border-left:4px solid ${farbe};
                 padding-left:10px; margin-top:25px;">
        ${titel} (${items.length})
      </h3>
      <ul style="background:${hintergrund}; padding:15px 15px 15px 35px;
                 border-radius:4px; line-height:1.9; margin:0;">
        ${items.map(i => `<li>${i}</li>`).join('\n        ')}
      </ul>`;
  };

  return `
    <div style="font-family:Arial,sans-serif; max-width:820px; color:#333;">

      <div style="background:#2c3e50; color:white; padding:25px;
                  border-radius:8px 8px 0 0;">
        <h2 style="margin:0; font-size:22px;">
          🌤️ WetterExtended – Tägliche Analyse
        </h2>
        <p style="margin:8px 0 0; opacity:.8; font-size:13px;">📅 ${zeit}</p>
      </div>

      <div style="padding:25px; border:1px solid #ddd; border-top:none;">

        ${data.fehler && data.fehler.length > 0
          ? section('❌ Fehler',           '#e74c3c', '#fff5f5', data.fehler)
          : '<p style="background:#f0fff0; color:#27ae60; padding:15px; border-radius:4px; margin:0;">✅ Keine Fehler gefunden!</p>'
        }

        ${section('✅ Lösungsvorschläge',       '#27ae60', '#f0fff0', data.loesungen)}
        ${section('💡 Verbesserungen',           '#3498db', '#f0f8ff', data.verbesserungen)}
        ${section('📝 Erstellte Code-Prompts',   '#8e44ad', '#faf0ff', data.prompts)}

        ${data.zusammenfassung ? `
          <h3 style="color:#e67e22; border-left:4px solid #e67e22;
                     padding-left:10px; margin-top:25px;">
            📋 Zusammenfassung
          </h3>
          <div style="background:#fff9f0; padding:15px; border-radius:4px;
                      line-height:1.8;">
            ${data.zusammenfassung}
          </div>` : ''}

      </div>

      <div style="background:#ecf0f1; padding:14px; text-align:center;
                  border-radius:0 0 8px 8px; font-size:12px; color:#7f8c8d;">
        🤖 Claude Code Routine &bull; IVOBLA/WetterExtended &bull;
        Täglich 13:00 Uhr GMT+2
      </div>

    </div>`;
}

// Mail versenden
async function sendMail() {
  const datum = new Date().toLocaleDateString('de-AT');

  try {
    // SMTP-Verbindung vorab prüfen
    await transporter.verify();
    console.log('SMTP-Verbindung OK.');

    const info = await transporter.sendMail({
      from:    '"WetterExtended Bot" <claude@blatec.at>',
      to:      'bla@uniquare.com',
      subject: `WetterExtended Analyse ${datum}`,
      html:    buildHtml(analysis),
      text:    JSON.stringify(analysis, null, 2)
    });

    console.log('E-Mail erfolgreich versendet.');
    console.log('Message-ID:', info.messageId);
    process.exit(0);

  } catch (error) {
    console.error('E-Mail-Versand fehlgeschlagen:', error.message);
    process.exit(1);
  }
}

sendMail();
