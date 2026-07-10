/**
 * Puppeteer cache configuration for WinZapp.
 *
 * Keeps the Chrome/Chromium binary inside the api/ directory so WinZapp
 * is self-contained and does not scatter files in the user's home folder.
 * This file is read by Puppeteer's postinstall script during `npm install`
 * and overrides the default cache location (~/.cache/puppeteer on Linux/macOS
 * or %LOCALAPPDATA%\puppeteer on Windows).
 *
 * The PUPPETEER_CACHE_DIR environment variable (set by WinZapp's Python layer
 * before launching the Node server) must point to the same directory so that
 * Puppeteer finds the binary at runtime.
 */
const path = require('path');

module.exports = {
  cacheDirectory: path.join(__dirname, '.cache', 'puppeteer'),
};
