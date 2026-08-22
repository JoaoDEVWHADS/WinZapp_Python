import {
  classifyPageError,
  DomainError,
  NotFoundError,
  SessionNotReadyError,
} from '../../errors/domain';
import { errorHandler } from '../../middleware/errorHandler';

function mockRes() {
  const state: any = { statusCode: 0, body: null, headersSent: false };
  const res: any = {
    get statusCode() {
      return state.statusCode;
    },
    get headersSent() {
      return state.headersSent;
    },
    set headersSent(value: boolean) {
      state.headersSent = value;
    },
    status(code: number) {
      state.statusCode = code;
      return res;
    },
    json(payload: any) {
      state.body = payload;
      return res;
    },
    get body() {
      return state.body;
    },
  };
  return res;
}

function mockReq(logged: string[] = []) {
  return {
    method: 'GET',
    originalUrl: '/api/session:token/get-messages/5511@c.us?count=200',
    logger: {
      warn: (m: string) => logged.push(`warn:${m}`),
      error: (m: string) => logged.push(`error:${m}`),
    },
  } as any;
}

describe('classifyPageError', () => {
  it('recognises a missing chat', () => {
    const error = classifyPageError(new Error('Chat not found for 55@c.us'));
    expect(error).toBeInstanceOf(NotFoundError);
    expect(error.httpStatus).toBe(404);
    expect(error.reason).toBe('not_found');
  });

  it('recognises a page that is not ready', () => {
    // The one case the old blanket 401 was really about.
    for (const message of [
      'WAPI is not defined',
      'Session closed',
      'Execution context was destroyed',
      'Target closed',
    ]) {
      expect(classifyPageError(new Error(message))).toBeInstanceOf(
        SessionNotReadyError
      );
    }
  });

  it('treats anything else as an internal error', () => {
    const error = classifyPageError(new Error('boom'));
    expect(error.reason).toBe('internal_error');
    expect(error.httpStatus).toBe(500);
  });

  it('survives being handed something that is not an Error', () => {
    expect(classifyPageError(undefined).reason).toBe('internal_error');
    expect(classifyPageError('just a string').reason).toBe('internal_error');
  });
});

describe('DomainError', () => {
  it('keeps instanceof working after transpilation', () => {
    // Subclassing a built-in loses the prototype chain when compiled down,
    // which would make the middleware treat every domain error as an unknown
    // crash and answer 500.
    const error = new NotFoundError('gone');
    expect(error instanceof NotFoundError).toBe(true);
    expect(error instanceof DomainError).toBe(true);
    expect(error instanceof Error).toBe(true);
  });
});

describe('errorHandler', () => {
  it('answers with the status and reason the domain error carries', () => {
    const res = mockRes();

    errorHandler(
      new NotFoundError('no such chat'),
      mockReq(),
      res,
      () => undefined
    );

    expect(res.statusCode).toBe(404);
    expect(res.body).toEqual({
      status: 'error',
      reason: 'not_found',
      message: 'no such chat',
    });
  });

  it('classifies an unknown error rather than guessing 500 blindly', () => {
    const res = mockRes();

    errorHandler(
      new Error('WAPI is not defined'),
      mockReq(),
      res,
      () => undefined
    );

    expect(res.statusCode).toBe(503);
    expect(res.body.reason).toBe('session_not_ready');
  });

  it('logs a 4xx as a warning and a 5xx as an error', () => {
    // A 4xx is the caller being told something true about their request;
    // giving each one a stack buries the ones that matter.
    const logged: string[] = [];
    errorHandler(
      new NotFoundError('gone'),
      mockReq(logged),
      mockRes(),
      () => undefined
    );
    expect(logged[0]).toMatch(/^warn:/);

    const logged5xx: string[] = [];
    errorHandler(
      new DomainError('internal_error', 'boom', 500),
      mockReq(logged5xx),
      mockRes(),
      () => undefined
    );
    expect(logged5xx[0]).toMatch(/^error:/);
  });

  it('hands the error on when the response has already started', () => {
    // Express's contract: once headers are out, the error cannot become a
    // body any more.
    const res = mockRes();
    res.headersSent = true;
    let passed: any = null;

    errorHandler(new NotFoundError('gone'), mockReq(), res, (e: any) => {
      passed = e;
    });

    expect(passed).toBeInstanceOf(NotFoundError);
    expect(res.statusCode).toBe(0);
  });

  it('includes details only when there are any', () => {
    const res = mockRes();

    errorHandler(
      new NotFoundError('gone', { chatId: '55@c.us' }),
      mockReq(),
      res,
      () => undefined
    );

    expect(res.body.details).toEqual({ chatId: '55@c.us' });
  });
});
