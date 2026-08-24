#!/usr/bin/env node
/**
 * Génère la valeur à mettre dans DASHBOARD_PASSWORD_HASH (Module 1, §7).
 * Usage : node generate-password-hash.js "votre-mot-de-passe"
 */
const { randomBytes, scryptSync } = require("crypto");

const password = process.argv[2];
if (!password) {
  console.error('Usage : node generate-password-hash.js "votre-mot-de-passe"');
  process.exit(1);
}

const salt = randomBytes(16).toString("hex");
const hash = scryptSync(password, salt, 64).toString("hex");

console.log(`${salt}:${hash}`);
