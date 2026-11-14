import type { Request, Response } from 'express';

// The buyer's one answer to an order a seller created: "Confirm order info".
//
// Read over CDP on 2026-10-19 (WhatsApp Web's order details drawer,
// WAWebOrderDetailDrawerContainer.react). The seller's order arrives as an
// interactive "order_details" message; the buyer's drawer shows a button only
// when the account is not the seller, the order is still "pending", it has
// items and a subtotal, and the consumer orders expansion has countries. That
// button is a payment action when the order carries one (a dynamic Pix code, a
// payment link or a boleto, each behind its own gate); only when it carries
// none, so the buyer pays outside the app, is it "Confirm order info", which
// calls WAWebBizSendOrderAction.sendOrderPaymentMethodUpdate with
// paymentMethod "confirm". That sends the seller an interactive
// "payment_method" message about the order (reference_id, payment_method
// "confirm"), quoting it. The same conditions are checked here, plus one
// WhatsApp Web does not check: a confirmation already sent for the order.
//
// Sent once, never retried: a send that threw may have reached the seller.
//
// Runs inside the page: self-contained, no closure over anything here.
export async function buyerOrderInPage(request: any): Promise<any> {
  const root = globalThis as any;
  const load = (name: string) => {
    try {
      return typeof root.require === 'function' ? root.require(name) : undefined;
    } catch (_) {
      return undefined;
    }
  };
  const modules = () => ({
    store: load('WAWebMsgCollection')?.MsgCollection,
    details: load('WAWebOrderDetails'),
    status: load('WAWebOrderStatus'),
    pay: load('WAWebBrPaymentSettingsUtils'),
    geo: load('WAWebBrazilPaymentsGeoGating'),
    countries: load('WAWebOrdersExpansionCountries'),
    msgGetters: load('WAWebMsgGetters'),
    frontend: load('WAWebFrontendMsgGetters'),
    me: load('WAWebUserPrefsMeUser'),
    send: load('WAWebBizSendOrderAction'),
    offset: load('WAWebOrderDetailMathDefaultOffset'),
    methods: load('WAWebOrderPaymentStatus'),
  });
  let m: any = modules();
  if (Object.values(m).some((value) => !value)) {
    // Some of it belongs to the order drawer's code, loaded the first time
    // someone opens an order in WhatsApp Web. Loading it shows nothing.
    // Bounded, as statusDeleteController.ts's Bootloader wait: a page that
    // never answers would keep one request hanging per window opened.
    let timer: any;
    try {
      await Promise.race([
        load('WAWebProductDetailsFlowLoadable')?.requireBundle?.(),
        new Promise((_, fail) => { timer = setTimeout(() => fail(new Error('unavailable')), 15000); }),
      ]);
    } catch (_) {
      // Answered below: still missing.
    } finally {
      clearTimeout(timer);
    }
    m = modules();
    if (Object.values(m).some((value) => !value)) return { error: 'unavailable' };
  }

  let msg = m.store.get(request.messageId);
  if (!msg && typeof root.WPP?.chat?.getMessageById === 'function') {
    try {
      await root.WPP.chat.getMessageById(request.messageId);
    } catch (_) {
      // Not in the chat: answered below.
    }
    msg = m.store.get(request.messageId);
  }
  if (!msg) return { error: 'not_an_order' };
  const raw = typeof msg.unsafe === 'function' ? msg.unsafe() : msg;
  // The seller's order itself: getOrderInfo() is not trusted to come back
  // empty for its other interactive messages (status, payment info).
  if ((msg.nativeFlowName ?? raw?.nativeFlowName) !== 'order_details') return { error: 'not_an_order' };
  let info: any = null;
  try {
    info = m.details.getOrderInfo(msg);
  } catch (_) {
    info = null;
  }
  if (!info || typeof info.referenceId !== 'string') return { error: 'not_an_order' };
  const chat = m.frontend.getChat(raw);
  const seller = m.msgGetters.getSender(raw);
  if (!chat || !seller) return { error: 'unavailable' };

  const orderStatus = m.status.findOrderStatus(chat, info.referenceId);
  const paysInApp = m.pay.hasValidDynamicPix(info) === true
    || (m.geo.isPaymentLinkEnabled(chat) === true && m.pay.hasValidPaymentLink(info) === true)
    || (m.geo.isBoletoEnabled(chat) === true && m.pay.hasValidBoletoCode(info) === true);
  const countries = m.countries.getConsumerOrdersExpansionAllowedCountries();
  const confirmed = (chat.msgs?.getModelsArray?.() ?? []).some((other: any) => {
    if (other?.id?.fromMe !== true || other.nativeFlowName !== 'payment_method') return false;
    try {
      const params = JSON.parse(other.interactivePayload?.buttons?.[0]?.buttonParamsJson || '{}');
      return params?.reference_id === info.referenceId && params?.payment_method === 'confirm';
    } catch (_) {
      return false;
    }
  });
  const canConfirm = m.me.isMeAccount(seller) !== true
    && orderStatus === 'pending'
    && Array.isArray(countries) && countries.length > 0
    && Array.isArray(info.items) && info.items.length > 0
    && info.subtotal != null
    && !paysInApp
    && !confirmed;

  if (request.action === 'read') return { canConfirm, confirmed };
  if (!canConfirm) return { error: confirmed ? 'already_confirmed' : 'cannot_confirm' };
  try {
    await m.send.sendOrderPaymentMethodUpdate({
      chat, offset: m.offset.DEFAULT_OFFSET, orderInfo: info, orderNote: null, orderStatus,
      paymentMethod: m.methods.OrderPaymentMethod.Confirm, paymentStatus: null, sellerJid: seller.toJid(),
    });
  } catch (_) {
    return { error: 'confirm_unconfirmed' };
  }
  return { confirmed: true };
}

// "true_<chat>_<id>" or "false_<chat>_<id>", a message of a one-to-one chat.
const validMessage = (value: unknown): value is string =>
  typeof value === 'string' && /^(true|false)_\d+@(c\.us|lid)_[A-Za-z0-9]{8,64}$/.test(value);

const STATUS_OF: Record<string, number> = {
  not_an_order: 404, already_confirmed: 409, cannot_confirm: 409, confirm_unconfirmed: 502,
};

async function run(req: Request, res: Response, action: 'read' | 'confirm') {
  if (!validMessage(req.params.messageId)) {
    return res.status(400).json({ status: 'error', code: 'invalid_request' });
  }
  try {
    const page: any = (req.client as any)?.page;
    if (!page || page.isClosed?.()) throw new Error('unavailable');
    const answer = await page.evaluate(buyerOrderInPage, { action, messageId: req.params.messageId });
    if (!answer || typeof answer !== 'object') throw new Error('unavailable');
    if (typeof answer.error === 'string') {
      const status = STATUS_OF[answer.error];
      if (!status) throw new Error('unavailable');
      return res.status(status).json({ status: 'error', code: answer.error });
    }
    return res.status(200).json({ status: 'success', response: answer });
  } catch (_) {
    // Never the native error: it can carry a chat id.
    return res.status(503).json({ status: 'error', code: 'commerce_unavailable' });
  }
}

export const readBuyerOrder = (req: Request, res: Response) => run(req, res, 'read');
export const confirmBuyerOrder = (req: Request, res: Response) => run(req, res, 'confirm');
