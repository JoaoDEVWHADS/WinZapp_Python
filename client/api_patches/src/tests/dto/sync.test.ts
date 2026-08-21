import { Logger } from 'winston';

import {
  observePayload,
  StatusSessionSchema,
  SyncChatListSchema,
  SyncMessageListSchema,
} from '../../dto/sync';

function mockLogger() {
  const warnings: string[] = [];
  const logger = {
    warn: (message: string) => warnings.push(message),
  } as unknown as Logger;
  return { logger, warnings };
}

describe('observePayload', () => {
  it('returns the exact object it was given, untouched', () => {
    const { logger } = mockLogger();
    const payload = [
      { id: 'true_5511@c.us_ABC', extraFieldWeNeverModelled: 1 },
    ];

    const result = observePayload(SyncMessageListSchema, payload, {
      logger,
      endpoint: 'get-messages',
    });

    // Identity, not deep equality: handing back zod's rebuilt copy would let
    // this middleware change what the Python client receives.
    expect(result).toBe(payload);
    expect((result as any)[0].extraFieldWeNeverModelled).toBe(1);
  });

  it('says nothing when the payload matches', () => {
    const { logger, warnings } = mockLogger();

    observePayload(
      SyncMessageListSchema,
      [{ id: { _serialized: 'true_5511@c.us_ABC' }, from: '5511@c.us', t: 1 }],
      { logger, endpoint: 'get-messages' }
    );

    expect(warnings).toEqual([]);
  });

  it('logs the historical id-less message instead of dropping it', () => {
    // The regression this whole module exists for: WhatsApp Web renamed
    // MsgKey._serialized to $1, WPPConnect serialised `id: undefined`, and the
    // message was silently discarded three layers away in Python.
    const { logger, warnings } = mockLogger();
    const payload = [{ from: '5511@c.us', body: 'oi', t: 1 }];

    const result = observePayload(SyncMessageListSchema, payload, {
      logger,
      endpoint: 'get-messages',
    });

    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain('get-messages');
    expect(warnings[0]).toContain('0.id');
    // Still delivered: observe mode never withholds a payload.
    expect(result).toBe(payload);
  });

  it('accepts a list-chats item with msgs null', () => {
    const { logger, warnings } = mockLogger();

    observePayload(
      SyncChatListSchema,
      [{ id: '5511@c.us', name: 'Bruna', unreadCount: 0, msgs: null }],
      { logger, endpoint: 'list-chats' }
    );

    expect(warnings).toEqual([]);
  });

  it('flags a status-session without its status field', () => {
    const { logger, warnings } = mockLogger();

    observePayload(
      StatusSessionSchema,
      { qrcode: null },
      {
        logger,
        endpoint: 'status-session',
      }
    );

    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain('status');
  });

  it('survives a schema that throws and still returns the payload', () => {
    const { logger, warnings } = mockLogger();
    const exploding = {
      safeParse: () => {
        throw new Error('boom');
      },
    } as any;
    const payload = { anything: true };

    const result = observePayload(exploding, payload, {
      logger,
      endpoint: 'list-chats',
    });

    expect(result).toBe(payload);
    expect(warnings[0]).toContain('check failed to run');
  });

  it('works with no logger at all', () => {
    const payload = [{ nope: true }];
    expect(
      observePayload(SyncMessageListSchema, payload, {
        endpoint: 'get-messages',
      })
    ).toBe(payload);
  });
});
