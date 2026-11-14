import {
  listCommunities, readCommunities, refreshCommunity, refreshUnjoinedSubgroups,
} from '../../controller/communityOverviewController';

function response() {
  const res: any = { statusCode: 0, body: null };
  res.status = (code: number) => { res.statusCode = code; return res; };
  res.json = (body: unknown) => { res.body = body; return res; };
  return res;
}
const wid = (value: string) => ({ _serialized: value, toString: () => value });
function participants(list: any[], me?: { admin?: boolean; superAdmin?: boolean }) {
  return {
    getModelsArray: () => list,
    iAmAdmin: () => !!me?.admin,
    iAmSuperAdmin: () => !!me?.superAdmin,
  };
}
function store(models: any[]) {
  const byId = new Map(models.map((m) => [m.id._serialized, m]));
  return { getModelsArray: () => models, get: (id: string) => byId.get(id) };
}
function withPage<T>(models: any[] | null, run: () => T): T {
  const previous = (globalThis as any).WPP;
  (globalThis as any).WPP = models ? { whatsapp: { GroupMetadataStore: store(models) } } : undefined;
  try { return run(); } finally { (globalThis as any).WPP = previous; }
}

const announcements = { id: wid('111-1@g.us'), subject: 'Avisos', defaultSubgroup: true };
const general = { id: wid('111-2@g.us'), subject: 'Geral', generalSubgroup: true };
const plain = { id: wid('111-3@g.us'), subject: 'Estudos' };
const community = {
  id: wid('111-0@g.us'), isParentGroup: true, subject: 'Escola', desc: 'Turma',
  isParentGroupClosed: true,
  joinedSubgroups: [announcements.id, general.id, plain.id, wid('999@lid'), wid('111-9@g.us')],
  participants: participants([
    { id: wid('5511@c.us'), isAdmin: true, isSuperAdmin: true },
    { id: wid('5522@c.us'), isAdmin: true },
    { id: wid('5533@c.us'), isAdmin: false },
  ], { admin: true }),
};
const ordinaryGroup = { id: wid('222-0@g.us'), subject: 'Família', participants: participants([]) };

test('lists each community with its admins and the groups joined', () => {
  const result: any = withPage([community, announcements, general, plain, ordinaryGroup], readCommunities);
  expect(result).toHaveLength(1);
  expect(result[0]).toMatchObject({
    id: '111-0@g.us', subject: 'Escola', description: 'Turma', closed: true,
    iAmAdmin: true, iAmSuperAdmin: false,
  });
  expect(result[0].admins).toEqual([
    { id: '5511@c.us', superAdmin: true },
    { id: '5522@c.us', superAdmin: false },
  ]);
});

test('the announcement group is the default subgroup, not a groupType WhatsApp Web no longer fills', () => {
  const result: any = withPage([community, announcements, general, plain], readCommunities);
  expect(result[0].subgroups).toEqual([
    { id: '111-1@g.us', subject: 'Avisos', announcement: true, general: false, joined: true, approval: false },
    { id: '111-2@g.us', subject: 'Geral', announcement: false, general: true, joined: true, approval: false },
    { id: '111-3@g.us', subject: 'Estudos', announcement: false, general: false, joined: true, approval: false },
    // Joined but not loaded yet: listed, with no name to show.
    { id: '111-9@g.us', subject: '', announcement: false, general: false, joined: true, approval: false },
  ]);
});

test('an id that is not a group never reaches the client', () => {
  const odd = { ...community, id: wid('not-a-group@lid') };
  expect(withPage([odd], readCommunities)).toEqual([]);
  const result: any = withPage([community, announcements], readCommunities);
  expect(result[0].subgroups.map((s: any) => s.id)).not.toContain('999@lid');
});

test('admin status that cannot be read is "not an admin", never a guess', () => {
  const broken = { ...community, participants: { getModelsArray: () => { throw new Error('private'); } } };
  const result: any = withPage([broken], readCommunities);
  expect(result[0]).toMatchObject({ iAmAdmin: false, iAmSuperAdmin: false, admins: [] });
});

test('a page with no store answers nothing rather than an empty list', () => {
  expect(withPage(null, readCommunities)).toBeNull();
});

test('the route wraps the page answer and never joins, creates or changes anything', async () => {
  const evaluate = jest.fn().mockResolvedValue([{ id: '111-0@g.us' }]);
  const req: any = { client: { page: { isClosed: () => false, evaluate }, createCommunity: jest.fn() } };
  const res = response();
  await listCommunities(req, res);
  expect(res.statusCode).toBe(200);
  expect(res.body).toEqual({ status: 'success', response: [{ id: '111-0@g.us' }] });
  expect(evaluate).toHaveBeenCalledWith(readCommunities);
  expect(req.client.createCommunity).not.toHaveBeenCalled();
});

test.each([
  ['a closed page', { isClosed: () => true, evaluate: jest.fn() }],
  ['no store in the page', { isClosed: () => false, evaluate: jest.fn().mockResolvedValue(null) }],
  ['a native failure', { isClosed: () => false, evaluate: jest.fn().mockRejectedValue(new Error('private group name')) }],
])('%s is unavailable, with no native text in the answer', async (_name, page) => {
  const res = response();
  await listCommunities({ client: { page } } as any, res);
  expect(res.statusCode).toBe(503);
  expect(res.body).toEqual({ status: 'error', code: 'communities_unavailable' });
  expect(JSON.stringify(res.body)).not.toMatch(/private/);
});

function withUnjoined<T>(models: any[], unjoined: any[], run: () => T): T {
  const previous = (globalThis as any).require;
  const byId = new Map(unjoined.map((m) => [m.id._serialized, m]));
  (globalThis as any).require = (name: string) =>
    name === 'WAWebUnjoinedSubgroupMetadataCollection' ? { get: (id: string) => byId.get(id) } : undefined;
  try { return withPage(models, run); } finally { (globalThis as any).require = previous; }
}

const open = { id: wid('111-5@g.us'), subject: 'Esportes', membershipApprovalMode: false };
const approval = { id: wid('111-6@g.us'), subject: 'Diretoria', membershipApprovalMode: true };
const hidden = { id: wid('111-7@g.us'), subject: 'Oculto', hiddenSubgroup: true };
const withOthers = {
  ...community,
  unjoinedSubgroups: [open.id, approval.id, hidden.id, plain.id, wid('999@lid')],
};

test('the groups the account is not in are listed after the joined ones', () => {
  const result: any = withUnjoined([withOthers, announcements, general, plain], [open, approval, hidden],
    readCommunities);
  const others = result[0].subgroups.filter((group: any) => !group.joined);
  expect(others).toEqual([
    { id: '111-5@g.us', subject: 'Esportes', announcement: false, general: false, joined: false, approval: false, requested: false },
    { id: '111-6@g.us', subject: 'Diretoria', announcement: false, general: false, joined: false, approval: true, requested: false },
    // Hidden: shown to admins only, and this account is one.
    { id: '111-7@g.us', subject: 'Oculto', announcement: false, general: false, joined: false, approval: false, requested: false },
  ]);
});

test('a hidden group is not listed for someone who is not an admin', () => {
  const member = { ...withOthers, participants: participants([], { admin: false }) };
  const result: any = withUnjoined([member], [open, hidden], readCommunities);
  expect(result[0].subgroups.map((group: any) => group.id)).not.toContain('111-7@g.us');
});

test('the refresh asks WhatsApp the way WhatsApp Web does, and only for a community', async () => {
  const query = jest.fn().mockResolvedValue(undefined);
  const root = globalThis as any;
  const previous = { require: root.require, WPP: root.WPP };
  root.require = (name: string) =>
    name === 'WAWebQuerySubGroupAction' ? { queryAndUpdateSubgroupsMetadata: query } : undefined;
  root.WPP = { whatsapp: { GroupMetadataStore: store([community, ordinaryGroup]) } };
  try {
    expect(await refreshUnjoinedSubgroups('111-0@g.us')).toBe(true);
    expect(query).toHaveBeenCalledWith(community.id, community.joinedSubgroups);
    expect(await refreshUnjoinedSubgroups('222-0@g.us')).toBe(false);
    expect(query).toHaveBeenCalledTimes(1);
  } finally {
    root.require = previous.require;
    root.WPP = previous.WPP;
  }
});

test('the refresh route answers the one community, refreshed', async () => {
  const evaluate = jest.fn()
    .mockResolvedValueOnce(true)
    .mockResolvedValueOnce([{ id: '222-0@g.us' }, { id: '111-0@g.us', subgroups: [] }]);
  const req: any = { params: { communityId: '111-0@g.us' }, client: { page: { isClosed: () => false, evaluate } } };
  const res = response();
  await refreshCommunity(req, res);
  expect(evaluate).toHaveBeenNthCalledWith(1, refreshUnjoinedSubgroups, '111-0@g.us');
  expect(evaluate).toHaveBeenNthCalledWith(2, readCommunities);
  expect(res.statusCode).toBe(200);
  expect(res.body).toEqual({ status: 'success', response: [{ id: '111-0@g.us', subgroups: [] }] });
});

test.each([
  ['an id that is not a group', '999@lid', 400],
  ['a refresh WhatsApp refused', '111-0@g.us', 503],
])('%s is never a success', async (_name, communityId, code) => {
  const evaluate = jest.fn().mockResolvedValueOnce(false);
  const res = response();
  await refreshCommunity({ params: { communityId }, client: { page: { isClosed: () => false, evaluate } } } as any, res);
  expect(res.statusCode).toBe(code);
});
