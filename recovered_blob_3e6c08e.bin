/**
 * WinZapp – Evolution API local launcher
 *
 * This script is executed by the bundled Node.js runtime when WinZapp
 * starts.  It:
 *   1. Starts an embedded PostgreSQL instance (first run: initialises
 *      the data directory; subsequent runs: resumes existing data).
 *   2. Runs Prisma migrations (safe to re-run – only applies new ones).
 *   3. Loads the pre-built Evolution API (dist/main).
 *
 * Environment variables that MUST be set before Evolution's own dotenv
 * call (dotenv does not override variables already present in process.env):
 *   DATABASE_CONNECTION_URI  – set here after PG starts
 *   SERVER_PORT              – set here to 3414
 *   SERVER_URL               – set here accordingly
 */

'use strict';

const path = require('path');
const fs   = require('fs');
const { execFileSync } = require('child_process');

// ── Paths ──────────────────────────────────────────────────────────────────
const API_DIR       = __dirname;                                // …/api/
const PG_DATA_DIR   = path.join(API_DIR, 'pgdata');            // …/api/pgdata/
const DIST_MAIN     = path.join(API_DIR, 'dist', 'main.js');
const PRISMA_CLI    = path.join(API_DIR, 'node_modules', 'prisma', 'build', 'index.js');
const PRISMA_SCHEMA = path.join(API_DIR, 'prisma', 'postgresql-schema.prisma');

// ── Embedded PostgreSQL config ─────────────────────────────────────────────
const PG_PORT = 5433;
const PG_USER = 'evolution';
const PG_PASS = 'evolution';
const PG_DB   = 'evolution_db';
const DB_URI  = `postgresql://${PG_USER}:${PG_PASS}@127.0.0.1:${PG_PORT}/${PG_DB}?schema=evolution_api`;

// ── Set critical environment variables BEFORE Evolution loads dotenv ────────
// dotenv does not override variables already in process.env, so these take
// precedence over whatever is written in api/.env.
process.env.DATABASE_CONNECTION_URI = DB_URI;
process.env.DATABASE_PROVIDER       = 'postgresql';
process.env.SERVER_PORT             = '3414';
process.env.SERVER_URL              = 'http://127.0.0.1:3414';
process.env.SERVER_TYPE             = 'http';

async function main() {
  // ── 1. Start embedded PostgreSQL ─────────────────────────────────────────
  let EmbeddedPostgres;
  try {
    EmbeddedPostgres = require('embedded-postgres').default;
  } catch (e) {
    console.error('[WinZapp] embedded-postgres not found – cannot start database.\n', e.message);
    process.exit(1);
  }

  const pg = new EmbeddedPostgres({
    databaseDir: PG_DATA_DIR,
    user:        PG_USER,
    password:    PG_PASS,
    port:        PG_PORT,
    persistent:  true,   // data survives process restarts
  });

  // initialise() calls initdb — only run it when the data directory does not
  // yet exist.  On subsequent launches the directory is already populated and
  // calling initdb again would fail with "directory is not empty".
  if (!fs.existsSync(PG_DATA_DIR)) {
    try {
      await pg.initialise();
    } catch (err) {
      console.error('[WinZapp] Failed to initialise embedded PostgreSQL:', err.message);
      process.exit(1);
    }
  }

  try {
    await pg.start();
  } catch (err) {
    console.error('[WinZapp] Failed to start embedded PostgreSQL:', err.message);
    process.exit(1);
  }

  // Create the application database (no-op if it already exists)
  try {
    await pg.createDatabase(PG_DB);
  } catch (_) { /* already exists – fine */ }

  // ── 2. Run Prisma migrations ──────────────────────────────────────────────
  try {
    execFileSync(
      process.execPath,
      [PRISMA_CLI, 'migrate', 'deploy', '--schema', PRISMA_SCHEMA],
      { cwd: API_DIR, env: process.env, stdio: 'pipe' }
    );
  } catch (err) {
    // Migrations may already be up-to-date; log but continue.
    console.warn('[WinZapp] Prisma migrate warning:', err.message);
  }

  // ── 3. Start Evolution API ────────────────────────────────────────────────
  try {
    require(DIST_MAIN);
  } catch (err) {
    console.error('[WinZapp] Failed to load Evolution API:', err);
    process.exit(1);
  }

  // Graceful shutdown: stop PG when the Node process exits
  process.on('exit',    () => { try { pg.stop(); } catch (_) {} });
  process.on('SIGINT',  () => { try { pg.stop(); } catch (_) {} process.exit(0); });
  process.on('SIGTERM', () => { try { pg.stop(); } catch (_) {} process.exit(0); });
}

main().catch(err => {
  console.error('[WinZapp] Fatal startup error:', err);
  process.exit(1);
});
