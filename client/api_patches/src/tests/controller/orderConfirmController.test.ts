import { buyerOrderInPage, confirmBuyerOrder } from '../../controller/orderConfirmController';

const ID = 'false_5511900000001@c.us_3EB0AAAAAAAAAAAA';

function fakePage({
  status = 'pending', mine = false, items = [{ id: 'custom-item-1', name: 'Bread' }], subtotal = 20,
  pix = false, link = false, boleto = false, countries = ['BR'], sent = [] as any[], present = true,
  sendFails = false, lazy = false, flow = 'order_details', hang = false,
}: any = {}) {
  const sender = { toJid: () => '5511900000001@c.us' };
  const info = { referenceId: 'REF1', items, subtotal };
  const chat = { msgs: { getModelsArray: () => sent } };
  const msg = { unsafe: () => msg, nativeFlowName: flow };
  const send = jest.fn(async () => {
    if (sendFails) throw new Error('SendMsgResult failure');
  });
  let bundle = !lazy;
  const requireBundle = jest.fn(() => (hang ? new Promise(() => {}) : Promise.resolve().then(() => { bundle = true; })));
  const modules: Record<string, any> = {
    WAWebMsgCollection: { MsgCollection: { get: (id: string) => (present && id === ID ? msg : undefined) } },
    WAWebOrderDetails: { getOrderInfo: () => info },
    WAWebOrderStatus: { findOrderStatus: () => status },
    WAWebBrPaymentSettingsUtils: { hasValidDynamicPix: () => pix, hasValidPaymentLink: () => link,
                                   hasValidBoletoCode: () => boleto },
    WAWebBrazilPaymentsGeoGating: { isPaymentLinkEnabled: () => true, isBoletoEnabled: () => true },
    WAWebOrdersExpansionCountries: { getConsumerOrdersExpansionAllowedCountries: () => countries },
    WAWebMsgGetters: { getSender: () => sender },
    WAWebFrontendMsgGetters: { getChat: () => chat },
    WAWebUserPrefsMeUser: { isMeAccount: () => mine },
    WAWebBizSendOrderAction: { sendOrderPaymentMethodUpdate: send },
    WAWebOrderDetailMathDefaultOffset: { DEFAULT_OFFSET: 1000 },
    WAWebOrderPaymentStatus: { OrderPaymentMethod: { Confirm: 'confirm' } },
    WAWebProductDetailsFlowLoadable: { requireBundle },
  };
  const require = (name: string) => {
    if (!bundle && name === 'WAWebBrPaymentSettingsUtils') throw new Error('not loaded');
    if (!(name in modules)) throw new Error('unknown');
    return modules[name];
  };
  return { require, send, requireBundle, chat, info, sender };
}

async function inPage(fake: any, action: 'read' | 'confirm', messageId = ID) {
  const root = globalThis as any;
  const previous = root.require;
  root.require = fake.require;
  try {
    return await buyerOrderInPage({ action, messageId });
  } finally {
    root.require = previous;
  }
}

const confirmation = (reference = 'REF1', method = 'confirm', fromMe = true) => ({
  id: { fromMe }, nativeFlowName: 'payment_method',
  interactivePayload: { buttons: [{ buttonParamsJson: JSON.stringify({ reference_id: reference, payment_method: method }) }] },
});

test('a pending order paid outside the app can be confirmed, the way WhatsApp Web does', async () => {
  const fake = fakePage();
  expect(await inPage(fake, 'read')).toEqual({ canConfirm: true, confirmed: false });
  expect(await inPage(fake, 'confirm')).toEqual({ confirmed: true });
  expect(fake.send).toHaveBeenCalledTimes(1);
  expect(fake.send).toHaveBeenCalledWith({
    chat: fake.chat, offset: 1000, orderInfo: fake.info, orderNote: null, orderStatus: 'pending',
    paymentMethod: 'confirm', paymentStatus: null, sellerJid: '5511900000001@c.us' });
});

test.each([
  ['an order with a dynamic Pix code', { pix: true }],
  ['an order with a payment link', { link: true }],
  ['an order with a boleto', { boleto: true }],
  ['an order past pending', { status: 'shipped' }],
  ['the account own order', { mine: true }],
  ['an order without items', { items: [] }],
  ['an order without a subtotal', { subtotal: null }],
  ['no consumer orders countries', { countries: [] }],
])('%s is never confirmed', async (_name, options) => {
  const fake = fakePage(options);
  expect(await inPage(fake, 'read')).toEqual({ canConfirm: false, confirmed: false });
  expect(await inPage(fake, 'confirm')).toEqual({ error: 'cannot_confirm' });
  expect(fake.send).not.toHaveBeenCalled();
});

test('an order the account already confirmed is not confirmed twice', async () => {
  const fake = fakePage({ sent: [confirmation()] });
  expect(await inPage(fake, 'read')).toEqual({ canConfirm: false, confirmed: true });
  expect(await inPage(fake, 'confirm')).toEqual({ error: 'already_confirmed' });
  expect(fake.send).not.toHaveBeenCalled();
});

test("another order's confirmation, the seller's, or another method do not count", async () => {
  const fake = fakePage({ sent: [confirmation('OTHER'), confirmation('REF1', 'confirm', false),
                                 confirmation('REF1', 'payment_instruction')] });
  expect(await inPage(fake, 'read')).toEqual({ canConfirm: true, confirmed: false });
});

test('a send that failed is unconfirmed, never retried', async () => {
  const fake = fakePage({ sendFails: true });
  expect(await inPage(fake, 'confirm')).toEqual({ error: 'confirm_unconfirmed' });
  expect(fake.send).toHaveBeenCalledTimes(1);
});

test("the order drawer's code is loaded when nobody opened an order yet", async () => {
  const fake = fakePage({ lazy: true });
  expect(await inPage(fake, 'read')).toEqual({ canConfirm: true, confirmed: false });
  expect(fake.requireBundle).toHaveBeenCalledTimes(1);
});

test('a message that is not loaded or not an order is not an order', async () => {
  expect(await inPage(fakePage({ present: false }), 'read')).toEqual({ error: 'not_an_order' });
});

test.each(['order_status', 'payment_info', null])(
  'a seller message of another kind (%s) is not an order to confirm', async (flow) => {
    const fake = fakePage({ flow });
    expect(await inPage(fake, 'confirm')).toEqual({ error: 'not_an_order' });
    expect(fake.send).not.toHaveBeenCalled();
  });

test('a page that never loads the order drawer gives up instead of hanging', async () => {
  jest.useFakeTimers();
  try {
    const answer = inPage(fakePage({ lazy: true, hang: true }), 'read');
    await Promise.resolve();
    jest.advanceTimersByTime(15000);
    expect(await answer).toEqual({ error: 'unavailable' });
  } finally {
    jest.useRealTimers();
  }
});

test('the route refuses an id that is not a message id before touching the page', async () => {
  const res: any = { status: jest.fn(() => res), json: jest.fn(() => res) };
  const page = { evaluate: jest.fn(), isClosed: () => false };
  await confirmBuyerOrder({ params: { messageId: '../x' }, client: { page } } as any, res);
  expect(res.status).toHaveBeenCalledWith(400);
  expect(page.evaluate).not.toHaveBeenCalled();
});

test('the route maps a refusal to its code and never passes the native error on', async () => {
  const res: any = { status: jest.fn(() => res), json: jest.fn(() => res) };
  const page = { evaluate: jest.fn().mockResolvedValue({ error: 'already_confirmed' }), isClosed: () => false };
  await confirmBuyerOrder({ params: { messageId: ID }, client: { page } } as any, res);
  expect(res.status).toHaveBeenCalledWith(409);
  expect(res.json).toHaveBeenCalledWith({ status: 'error', code: 'already_confirmed' });

  const broken: any = { status: jest.fn(() => broken), json: jest.fn(() => broken) };
  const failing = { evaluate: jest.fn().mockRejectedValue(new Error('5511900000001@c.us')), isClosed: () => false };
  await confirmBuyerOrder({ params: { messageId: ID }, client: { page: failing } } as any, broken);
  expect(broken.status).toHaveBeenCalledWith(503);
  expect(JSON.stringify(broken.json.mock.calls)).not.toContain('5511900000001');
});
