import { EventEmitter } from 'events';
import { NextFunction, Request, Response } from 'express';
import { Logger } from 'winston';

import {
  metrics,
  prometheusRegister,
  requestInstrumentation,
} from '../../middleware/instrumentation';

class MockResponse extends EventEmitter {
  public body = '';
  public headers: Record<string, unknown> = {};
  public statusCode = 200;
  public writableEnded = false;

  setHeader(name: string, value: unknown) {
    this.headers[name.toLowerCase()] = value;
    return this;
  }

  status(code: number) {
    this.statusCode = code;
    return this;
  }

  send(data: string) {
    this.body = data;
    this.writableEnded = true;
    this.emit('finish');
    return this;
  }
}

function resetHttpMetrics() {
  prometheusRegister.getSingleMetric('winzapp_http_requests_total')?.reset();
  prometheusRegister
    .getSingleMetric('winzapp_http_request_duration_seconds')
    ?.reset();
  prometheusRegister.getSingleMetric('winzapp_http_active_requests')?.reset();
}

function loggerMock() {
  const child = {
    http: jest.fn(),
    warn: jest.fn(),
  };
  const logger = {
    child: jest.fn(() => child),
  } as unknown as Logger;
  return { child, logger };
}

describe('HTTP instrumentation', () => {
  beforeEach(resetHttpMetrics);

  it('propagates a valid request id and records the normalized route', async () => {
    const { child, logger } = loggerMock();
    const req = {
      baseUrl: '',
      headers: { 'x-request-id': 'sync-42' },
      method: 'post',
    } as unknown as Request;
    const res = new MockResponse();
    const next = jest.fn() as NextFunction;

    requestInstrumentation(logger)(req, res as unknown as Response, next);

    expect(next).toHaveBeenCalledTimes(1);
    expect(req.requestId).toBe('sync-42');
    expect(res.headers['x-request-id']).toBe('sync-42');
    expect(logger.child).toHaveBeenCalledWith({ requestId: 'sync-42' });

    req.route = { path: '/api/:session/messages' } as Request['route'];
    res.statusCode = 201;
    res.writableEnded = true;
    res.emit('finish');
    res.emit('close');

    expect(child.http).toHaveBeenCalledTimes(1);
    expect(child.warn).not.toHaveBeenCalled();

    const counter = await prometheusRegister
      .getSingleMetric('winzapp_http_requests_total')
      ?.get();
    expect(counter?.values).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          labels: expect.objectContaining({
            method: 'POST',
            route: '/api/:session/messages',
            status_code: '201',
          }),
          value: 1,
        }),
      ])
    );
  });

  it('replaces an unsafe request id and records an aborted request once', async () => {
    const { child, logger } = loggerMock();
    const req = {
      baseUrl: '',
      headers: { 'x-request-id': 'invalid id with spaces' },
      method: 'get',
    } as unknown as Request;
    const res = new MockResponse();

    requestInstrumentation(logger)(req, res as unknown as Response, jest.fn());
    res.emit('close');
    res.emit('close');

    expect(req.requestId).not.toBe('invalid id with spaces');
    expect(req.requestId).toMatch(/^[0-9a-f-]{36}$/);
    expect(child.warn).toHaveBeenCalledTimes(1);

    const counter = await prometheusRegister
      .getSingleMetric('winzapp_http_requests_total')
      ?.get();
    expect(counter?.values).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          labels: expect.objectContaining({
            method: 'GET',
            route: 'unmatched',
            status_code: 'aborted',
          }),
          value: 1,
        }),
      ])
    );
  });

  it('serves process and HTTP metrics from the persistent registry', async () => {
    const res = new MockResponse();

    await metrics({} as Request, res as unknown as Response);

    expect(res.statusCode).toBe(200);
    expect(res.headers['content-type']).toBe(prometheusRegister.contentType);
    expect(res.body).toContain('winzapp_node_process_cpu_user_seconds_total');
    expect(res.body).toContain('winzapp_http_requests_total');
    expect(res.body).toContain('winzapp_http_request_duration_seconds');
  });

  it('names the session without leaking the token that rides with it', async () => {
    // WPPConnect authenticates with `<session>:<token>` in the path, so
    // Express's :session param captures both. The log needs the name (a 10MB
    // file accumulated across runs and accounts is unusable without it) and
    // must never carry the credential.
    const logged: string[] = [];
    const logger = {
      child: () => ({
        warn: (m: string) => logged.push(m),
        http: (m: string) => logged.push(m),
      }),
    } as any;
    const req: any = {
      headers: {},
      method: 'GET',
      params: { session: 'mysession:$2b$10$supersecrettoken' },
      route: { path: '/api/:session/list-chats' },
      baseUrl: '',
    };
    const res = new MockResponse();

    requestInstrumentation(logger)(req, res as any, () => undefined);
    res.send('ok');
    await new Promise((resolve) => setImmediate(resolve));

    const output = logged.join(' | ');
    expect(output).toContain('session=mysession');
    expect(output).not.toContain('supersecrettoken');
  });
});
