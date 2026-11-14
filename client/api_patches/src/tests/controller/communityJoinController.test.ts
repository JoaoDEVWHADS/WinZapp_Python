import {
  cancelJoinRequest, communitySubgroupMembership, joinSubgroup,
} from '../../controller/communityJoinController';

class ServerStatusCodeError extends Error {
  status: number;
  constructor(status: number) { super('private'); this.status = status; }
}
class UnexpectedJoinSubgroupResponse extends Error {
  membershipApprovalMode: boolean;
  constructor(mode: boolean) { super('private'); this.membershipApprovalMode = mode; }
}

const wid = (value: string) => ({ _serialized: value, toString: () => value });
const COMMUNITY = '111-0@g.us';
const GROUP = '111-5@g.us';

function page({ info = {}, join = jest.fn().mockResolvedValue({ status: 200 }), cancel = jest.fn(),
                loaded = true }: any = {}) {
  const parent = { id: wid(COMMUNITY), isParentGroup: true };
  const update = jest.fn();
  const query = jest.fn().mockResolvedValue(info);
  let joinLoaded = loaded;
  const bootloader = { loadModules: jest.fn((_names: string[], done: () => void) => { joinLoaded = true; done(); }) };
  const modules: Record<string, () => any> = {
    WAWebJoinSubgroupAction: () => (joinLoaded ? { joinSubgroup: join } : undefined),
    WAWebQuerySubGroupAction: () => ({ querySubgroupInfo: query }),
    WAWebBackendErrors: () => ({ ServerStatusCodeError, UnexpectedJoinSubgroupResponse }),
    WAWebUpdateSubgroupsCommunityAction: () => ({ updateMembershipApprovalRequest: update }),
    WAWebMembershipApprovalRequestAction: () => ({ cancelMembershipApprovalRequest: cancel }),
    Bootloader: () => bootloader,
  };
  return { parent, update, query, join, cancel, bootloader, modules };
}

async function inPage(fake: any, args: any) {
  const root = globalThis as any;
  const previous = { WPP: root.WPP, require: root.require };
  root.WPP = { whatsapp: {
    GroupMetadataStore: { get: (id: string) => (id === COMMUNITY ? fake.parent : undefined) },
    WidFactory: { createWid: (id: string) => wid(id) },
  } };
  root.require = (name: string) => fake.modules[name]?.();
  try {
    return await communitySubgroupMembership(args);
  } finally {
    root.WPP = previous.WPP;
    root.require = previous.require;
  }
}

const join = { communityId: COMMUNITY, subgroupId: GROUP, operation: 'join' };

test('an open group is joined the way WhatsApp Web joins it', async () => {
  const fake = page({ info: { membershipApprovalMode: false } });
  expect(await inPage(fake, join)).toEqual({ ok: true, state: 'joined' });
  expect(fake.query.mock.calls[0][0].toString()).toBe(GROUP);
  expect(fake.query.mock.calls[0][1]).toBe(fake.parent.id);
  const [{ parentGroupId, request, subgroupId }] = fake.join.mock.calls[0];
  expect(parentGroupId).toBe(fake.parent.id);
  expect(request).toBe(false);
  expect(subgroupId.toString()).toBe(GROUP);
  expect(fake.update).not.toHaveBeenCalled();
});

test('a group that needs approval gets a request, recorded as pending', async () => {
  const fake = page({ info: { membershipApprovalMode: true } });
  expect(await inPage(fake, join)).toEqual({ ok: true, state: 'requested' });
  expect(fake.join.mock.calls[0][0].request).toBe(true);
  expect(fake.update.mock.calls[0][1]).toBe(true);
});

test.each([
  ['the server wanted a request', new UnexpectedJoinSubgroupResponse(true), 'requested'],
  ['the server let the account in', new UnexpectedJoinSubgroupResponse(false), 'joined'],
  ['a request already existed', new ServerStatusCodeError(304), 'request_pending'],
])('when %s, its answer is the one taken', async (_name, error, state) => {
  const fake = page({ join: jest.fn().mockRejectedValue(error) });
  expect(await inPage(fake, join)).toEqual({ ok: true, state });
});

test('a request already sent is not sent again', async () => {
  const fake = page({ info: { membershipApprovalRequest: true } });
  expect(await inPage(fake, join)).toEqual({ ok: true, state: 'request_pending' });
  expect(fake.join).not.toHaveBeenCalled();
});

test.each([
  ['suspended', { suspended: true }, 'group_unavailable'],
  ['hidden', { hiddenSubgroup: true }, 'hidden_group'],
])('a %s group is never joined', async (_name, info, code) => {
  const fake = page({ info });
  expect(await inPage(fake, join)).toEqual({ ok: false, code });
  expect(fake.join).not.toHaveBeenCalled();
});

test('any other failure is a failure, once, with no native text', async () => {
  const fake = page({ join: jest.fn().mockRejectedValue(new ServerStatusCodeError(500)) });
  const result = await inPage(fake, join);
  expect(result).toEqual({ ok: false, code: 'join_failed' });
  expect(fake.join).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(result)).not.toMatch(/private/);
});

test('the join modal code is loaded when nobody opened it yet', async () => {
  const fake = page({ loaded: false });
  expect(await inPage(fake, join)).toEqual({ ok: true, state: 'joined' });
  expect(fake.bootloader.loadModules.mock.calls[0][0]).toEqual(['WAWebSubgroupJoinModal.react']);
});

test('a request is withdrawn and recorded as gone', async () => {
  const fake = page();
  expect(await inPage(fake, { ...join, operation: 'cancel' })).toEqual({ ok: true, state: 'cancelled' });
  expect(fake.cancel.mock.calls[0][0].toString()).toBe(GROUP);
  expect(fake.update.mock.calls[0][1]).toBe(false);
  expect(fake.join).not.toHaveBeenCalled();
});

test.each([
  [{ ...join, subgroupId: '999@lid' }, 'invalid_request'],
  [{ ...join, operation: 'leave' }, 'invalid_request'],
  [{ ...join, communityId: '222-0@g.us' }, 'not_community'],
])('%o is refused before asking anything', async (args, code) => {
  const fake = page();
  expect(await inPage(fake, args)).toEqual({ ok: false, code });
  expect(fake.query).not.toHaveBeenCalled();
});

function response() {
  const res: any = { statusCode: 0, body: null };
  res.status = (code: number) => { res.statusCode = code; return res; };
  res.json = (body: unknown) => { res.body = body; return res; };
  return res;
}

test.each([
  [{ ok: true, state: 'joined' }, 200, { status: 'success', response: { state: 'joined' } }],
  [{ ok: false, code: 'hidden_group' }, 409, { status: 'error', code: 'hidden_group', retrySafe: false }],
  [{ ok: false, code: 'join_failed' }, 502, { status: 'error', code: 'join_failed', retrySafe: false }],
])('the route answers %o as HTTP %i', async (result, status, body) => {
  const evaluate = jest.fn().mockResolvedValue(result);
  const req: any = { params: { communityId: COMMUNITY, subgroupId: GROUP },
                     client: { page: { isClosed: () => false, evaluate } } };
  const res = response();
  await joinSubgroup(req, res);
  expect(evaluate).toHaveBeenCalledWith(communitySubgroupMembership,
    { communityId: COMMUNITY, subgroupId: GROUP, operation: 'join' });
  expect(res.statusCode).toBe(status);
  expect(res.body).toEqual(body);
});

test('cancelling goes through the same page function', async () => {
  const evaluate = jest.fn().mockResolvedValue({ ok: true, state: 'cancelled' });
  const req: any = { params: { communityId: COMMUNITY, subgroupId: GROUP },
                     client: { page: { isClosed: () => false, evaluate } } };
  await cancelJoinRequest(req, response());
  expect(evaluate.mock.calls[0][1].operation).toBe('cancel');
});
