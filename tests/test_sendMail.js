'use strict';

const assert = require('assert');
const Module = require('module');

const originalLoad = Module._load;
const originalExit = process.exit;
const originalArgv = process.argv;
const originalPassword = process.env.SMTP_PASSWORD;

let transporterOptions;
let verifyCalled = false;
let sentMail;
let exitCode;

Module._load = function mockedLoad(request, parent, isMain) {
  if (request === 'nodemailer') {
    return {
      createTransport(options) {
        transporterOptions = options;
        return {
          async verify() {
            verifyCalled = true;
          },
          async sendMail(mail) {
            sentMail = mail;
            return { messageId: 'test-message-id' };
          }
        };
      }
    };
  }

  return originalLoad.apply(this, arguments);
};

process.env.SMTP_PASSWORD = 'test-secret';
process.argv = [process.execPath, 'sendMail.js', JSON.stringify({
  fehler: ['Fehler A'],
  loesungen: ['Lösung A'],
  verbesserungen: ['Verbesserung A'],
  prompts: ['Prompt A'],
  zusammenfassung: 'Alles geprüft.'
})];
process.exit = (code) => {
  exitCode = code;
};

require('../sendMail');

setImmediate(() => {
  try {
    assert.strictEqual(exitCode, 0);
    assert.strictEqual(verifyCalled, true);
    assert.deepStrictEqual(transporterOptions, {
      host: 'w00eab71.kasserver.com',
      port: 587,
      secure: false,
      auth: {
        user: 'claude@blatec.at',
        pass: 'test-secret'
      },
      tls: {
        rejectUnauthorized: false
      }
    });
    assert.strictEqual(sentMail.from, '"WetterExtended Bot" <claude@blatec.at>');
    assert.strictEqual(sentMail.to, 'blaha540@gmail.com');
    assert.match(sentMail.subject, /^WetterExtended Analyse /);
    assert.match(sentMail.html, /WetterExtended – Tägliche Analyse/);
    assert.match(sentMail.html, /Fehler A/);
    assert.match(sentMail.html, /Lösung A/);
    assert.match(sentMail.html, /Verbesserung A/);
    assert.match(sentMail.html, /Prompt A/);
    assert.match(sentMail.html, /Alles geprüft\./);
    assert.strictEqual(JSON.parse(sentMail.text).zusammenfassung, 'Alles geprüft.');
  } finally {
    Module._load = originalLoad;
    process.exit = originalExit;
    process.argv = originalArgv;
    if (originalPassword === undefined) {
      delete process.env.SMTP_PASSWORD;
    } else {
      process.env.SMTP_PASSWORD = originalPassword;
    }
  }
});
