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
 *   SERVER_PORT              – set here to 3417
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
process.env.SERVER_PORT             = '3417';
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
    // Force UTF-8 on first-time cluster initialisation.
    // Without this, initdb on Windows defaults to WIN1252 and Postgres cannot
    // store emoji / multibyte characters (error code 22P05).
    initdbFlags: ['--encoding=UTF8'],
  });

  // pg.initialise() runs initdb, which fails if pgdata already exists.
  // We detect an existing cluster by the presence of the PG_VERSION marker
  // file that initdb always creates, and skip initialisation in that case.
  const pgVersionFile = path.join(PG_DATA_DIR, 'PG_VERSION');
  const pgAlreadyInit = fs.existsSync(pgVersionFile);

  try {
    if (!pgAlreadyInit) {
      await pg.initialise();
    }
    await pg.start();
  } catch (err) {
    console.error('[WinZapp] Failed to start embedded PostgreSQL:', err.message);
    process.exit(1);
  }

  // ── Ensure the application database exists with UTF-8 encoding ────────────
  //
  // On Windows, initdb defaults to WIN1252.  The fix is to create (or
  // recreate) the database from template0 with an explicit UTF-8 encoding.
  // Using template0 (not template1) is required when the target encoding
  // differs from the cluster default.
  //
  // If the database already exists with the wrong encoding we drop it first.
  // This means existing WhatsApp session data is lost, but:
  //   a) The cluster was already broken (all emoji writes failed).
  //   b) Baileys session credentials live in the 'instances/' file tree, not
  //      in Postgres, so WhatsApp pairing survives the database reset.
  {
    const adminClient = pg.getPgClient('postgres', '127.0.0.1');
    try {
      await adminClient.connect();

      const { rows } = await adminClient.query(
        `SELECT pg_encoding_to_char(encoding) AS enc
           FROM pg_database
          WHERE datname = $1`,
        [PG_DB]
      );

      if (rows.length === 0) {
        // Database does not yet exist — create with UTF-8.
        console.log('[WinZapp] Criando banco de dados com encoding UTF-8...');
        await adminClient.query(
          `CREATE DATABASE "${PG_DB}"
             ENCODING    'UTF8'
             LC_COLLATE  'C'
             LC_CTYPE    'C'
             TEMPLATE    template0`
        );
        console.log('[WinZapp] Banco de dados criado com sucesso (UTF-8).');

      } else if (rows[0].enc !== 'UTF8') {
        // Wrong encoding detected — drop and recreate.
        console.log(
          `[WinZapp] Encoding incorreto detectado (${rows[0].enc}). ` +
          'Recriando banco de dados com UTF-8...'
        );

        // Terminate any lingering connections to allow DROP DATABASE.
        await adminClient.query(
          `SELECT pg_terminate_backend(pid)
             FROM pg_stat_activity
            WHERE datname = $1 AND pid <> pg_backend_pid()`,
          [PG_DB]
        );

        await adminClient.query(`DROP DATABASE IF EXISTS "${PG_DB}"`);
        await adminClient.query(
          `CREATE DATABASE "${PG_DB}"
             ENCODING    'UTF8'
             LC_COLLATE  'C'
             LC_CTYPE    'C'
             TEMPLATE    template0`
        );
        console.log('[WinZapp] Banco de dados recriado com UTF-8. Re-pareamento do WhatsApp necessário.');

      } else {
        console.log('[WinZapp] Banco de dados OK (UTF-8).');
      }

    } catch (dbErr) {
      console.error('[WinZapp] Erro ao verificar/criar banco de dados:', dbErr.message);
    } finally {
      await adminClient.end().catch(() => {});
    }
  }

  // ── 2. Run Prisma migrations ──────────────────────────────────────────────
  // First, sync the provider-specific migrations folder into the generic
  // ./prisma/migrations path that Prisma expects.  This replicates what
  // `npm run db:deploy:win` does (xcopy step) but using Node's fs module so
  // it works on Windows without relying on Unix shell commands.
  const MIGRATIONS_SRC = path.join(API_DIR, 'prisma', 'postgresql-migrations');
  const MIGRATIONS_DST = path.join(API_DIR, 'prisma', 'migrations');
  try {
    if (fs.existsSync(MIGRATIONS_DST)) {
      fs.rmSync(MIGRATIONS_DST, { recursive: true, force: true });
    }
    if (fs.existsSync(MIGRATIONS_SRC)) {
      fs.cpSync(MIGRATIONS_SRC, MIGRATIONS_DST, { recursive: true });
    }
  } catch (err) {
    console.warn('[WinZapp] Could not sync migrations folder:', err.message);
  }

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
