/*
 * Copyright 2021 WPPConnect Team
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { randomUUID } from 'crypto';
import { NextFunction, Request, Response } from 'express';
import Prometheus from 'prom-client';
import { Logger } from 'winston';

const REQUEST_ID_HEADER = 'x-request-id';
const REQUEST_ID_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;
const SLOW_REQUEST_SECONDS = 2;

const register = new Prometheus.Registry();

register.setDefaultLabels({
  app: 'wppconnect-server',
});

Prometheus.collectDefaultMetrics({
  prefix: 'winzapp_node_',
  register,
});

const httpRequestsTotal = new Prometheus.Counter({
  name: 'winzapp_http_requests_total',
  help: 'Total number of HTTP requests handled by the embedded Node API.',
  labelNames: ['method', 'route', 'status_code'],
  registers: [register],
});

const httpRequestDuration = new Prometheus.Histogram({
  name: 'winzapp_http_request_duration_seconds',
  help: 'Duration of HTTP requests handled by the embedded Node API.',
  labelNames: ['method', 'route', 'status_code'],
  buckets: [0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60],
  registers: [register],
});

const httpActiveRequests = new Prometheus.Gauge({
  name: 'winzapp_http_active_requests',
  help: 'Number of HTTP requests currently being handled.',
  labelNames: ['method'],
  registers: [register],
});

// ── Where the time actually goes ────────────────────────────────────────────
//
// HTTP duration alone cannot answer "why is the sync slow": every endpoint
// here is a thin wrapper around work that happens inside the WhatsApp Web
// page, on a single JS thread shared with WhatsApp's own sync. A list-chats
// that takes 35 seconds spent ~all of it in one page.evaluate, and nothing
// recorded that. The buckets run to 60s deliberately — the pathological cases
// are the ones worth seeing, and they are measured in tens of seconds.
const pageEvaluateDuration = new Prometheus.Histogram({
  name: 'winzapp_page_evaluate_duration_seconds',
  help: 'Duration of work executed inside the WhatsApp Web page.',
  labelNames: ['operation', 'outcome'],
  buckets: [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120],
  registers: [register],
});

// Chats and messages are addressed by two identities (@lid and the phone JID)
// and the wrong one answers "not found". Every fallback taken is a measure of
// how often the first choice was wrong — the thing to watch when identity
// handling changes, and today invisible.
const jidFallbackTotal = new Prometheus.Counter({
  name: 'winzapp_jid_fallback_total',
  help: 'Times a lookup had to retry under a different JID form.',
  labelNames: ['operation', 'from_form', 'to_form'],
  registers: [register],
});

// Recoveries of an empty/invalid ChatStore, and what they managed to rebuild.
const storeRecoveryTotal = new Prometheus.Counter({
  name: 'winzapp_store_recovery_total',
  help: 'ChatStore recovery attempts, by outcome.',
  labelNames: ['outcome'],
  registers: [register],
});

/** The JID family a raw id belongs to, for a bounded label set. */
export function jidForm(jid: string): string {
  const value = String(jid || '');
  if (value.endsWith('@lid')) return 'lid';
  if (value.endsWith('@g.us')) return 'group';
  if (value.endsWith('@c.us') || value.endsWith('@s.whatsapp.net')) return 'phone';
  if (value.endsWith('@broadcast')) return 'broadcast';
  if (value.endsWith('@newsletter')) return 'newsletter';
  return 'other';
}

export function countJidFallback(
  operation: string,
  fromJid: string,
  toJid: string
): void {
  jidFallbackTotal.inc({
    operation,
    from_form: jidForm(fromJid),
    to_form: jidForm(toJid),
  });
}

export function countStoreRecovery(outcome: string): void {
  storeRecoveryTotal.inc({ outcome });
}

/**
 * Time one piece of in-page work.
 *
 * Wraps rather than replaces the call so the caller keeps its own error
 * handling: the promise's rejection is re-thrown untouched, only recorded
 * first — a failure that takes 30 seconds is exactly the sample worth having,
 * and dropping it would make the histogram describe only the happy path.
 */
export async function observeEvaluate<T>(
  operation: string,
  run: () => Promise<T>
): Promise<T> {
  const started = process.hrtime.bigint();
  const elapsed = () => Number(process.hrtime.bigint() - started) / 1_000_000_000;
  try {
    const result = await run();
    pageEvaluateDuration.observe({ operation, outcome: 'ok' }, elapsed());
    return result;
  } catch (error) {
    pageEvaluateDuration.observe({ operation, outcome: 'error' }, elapsed());
    throw error;
  }
}

function requestIdFromHeader(value: string | string[] | undefined): string {
  const candidate = Array.isArray(value) ? value[0] : value;
  return candidate && REQUEST_ID_PATTERN.test(candidate)
    ? candidate
    : randomUUID();
}

function routeLabel(req: Request): string {
  const routePath = req.route?.path;
  if (typeof routePath === 'string') {
    return `${req.baseUrl || ''}${routePath}` || '/';
  }
  return 'unmatched';
}

export function requestInstrumentation(logger: Logger) {
  return (req: Request, res: Response, next: NextFunction): void => {
    const requestId = requestIdFromHeader(req.headers[REQUEST_ID_HEADER]);
    const method = req.method.toUpperCase();
    const startedAt = process.hrtime.bigint();
    let finalized = false;

    req.requestId = requestId;
    req.logger = logger.child({ requestId });
    res.setHeader('X-Request-Id', requestId);
    httpActiveRequests.inc({ method });

    const finalize = (aborted: boolean) => {
      if (finalized) return;
      finalized = true;

      const durationSeconds =
        Number(process.hrtime.bigint() - startedAt) / 1_000_000_000;
      const route = routeLabel(req);
      const statusCode = aborted ? 'aborted' : String(res.statusCode);
      const labels = { method, route, status_code: statusCode };

      httpActiveRequests.dec({ method });
      httpRequestsTotal.inc(labels);
      httpRequestDuration.observe(labels, durationSeconds);

      // Which session this belonged to, so a 10MB log accumulated across runs
      // and accounts can be filtered down to one of them. Read here rather
      // than at the top of the middleware because Express only fills
      // req.params once a route has matched.
      //
      // Redacted deliberately: WPPConnect authenticates with
      // `<session>:<token>` in the path, so `:session` captures the credential
      // along with the name. Logging it whole would put the token in the API
      // log — the same mistake the Python side was making 2,360 times a run.
      const session = String(req.params?.session || '').split(':')[0];

      const message =
        `HTTP ${method} ${route} ${statusCode} ` +
        `${(durationSeconds * 1000).toFixed(1)}ms requestId=${requestId}` +
        (session ? ` session=${session}` : '');

      if (aborted || durationSeconds >= SLOW_REQUEST_SECONDS) {
        req.logger.warn(message);
      } else {
        req.logger.http(message);
      }
    };

    res.once('finish', () => finalize(false));
    res.once('close', () => finalize(!res.writableEnded));
    next();
  };
}

export async function metrics(_req: Request, res: Response): Promise<void> {
  /**
     #swagger.tags = ["Misc"]
     #swagger.autoBody=false
     #swagger.description = 'This endpoint can be used to check the status of API metrics. It returns a response with the collected metrics.'
     }
   */
  res.setHeader('Content-Type', register.contentType);
  res.status(200).send(await register.metrics());
}

export const prometheusRegister = register;
