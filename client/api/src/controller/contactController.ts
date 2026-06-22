import { Request, Response } from 'express';

export default class ContactController {
  static async getContactPnLid(req: Request, res: Response) {
    /**
      #swagger.tags = ["Contact"]
      #swagger.autoBody=false
      #swagger.security = [{
              "bearerAuth": []
      }]
      #swagger.parameters["session"] = {
          schema: 'NERDWHATS_AMERICA'
      }
      #swagger.parameters["pnLid"] = {
          schema: '1234567890@c.us' // or '1234567890@lid'
      }
      */
    const { pnLid } = req.params;

    if (!pnLid) {
      return res.status(400).json({
        status: 'error',
        message: 'Phone Number or LID (pnLid) parameter is required',
      });
    }

    try {
      let response = await req.client.getPnLidEntry(pnLid) as any;
      let pnJid = response?.contact?.id?._serialized || response?.contact?.id || null;

      if (!pnJid) {
        try {
          if (typeof (req.client as any).requestPhoneNumber === 'function') {
            req.logger.info(`Requesting phone number for ${pnLid} via client.requestPhoneNumber`);
            await (req.client as any).requestPhoneNumber(pnLid);
            response = await req.client.getPnLidEntry(pnLid) as any;
            pnJid = response?.contact?.id?._serialized || response?.contact?.id || null;
          } else if (req.client.page) {
            req.logger.info(`Requesting phone number for ${pnLid} via browser WPP.chat.requestPhoneNumber`);
            await req.client.page.evaluate(async (id: string) => {
              const w = window as any;
              if (w.WPP && w.WPP.chat && typeof w.WPP.chat.requestPhoneNumber === 'function') {
                await w.WPP.chat.requestPhoneNumber(id);
              }
            }, pnLid);
            response = await req.client.getPnLidEntry(pnLid) as any;
            pnJid = response?.contact?.id?._serialized || response?.contact?.id || null;
          }
        } catch (reqError) {
          req.logger.error('Error requesting phone number for LID: ' + pnLid, reqError);
        }
      }

      res.status(200).json({
        ...response,
        pnJid: pnJid,
        contact: response?.contact ? {
          ...response.contact,
          id: response.contact.id ? {
            id: response.contact.id.id,
            server: response.contact.id.server,
            _serialized: response.contact.id._serialized
          } : null
        } : null
      });
    } catch (error) {
      req.logger.error(error);
      res.status(500).json({
        status: 'error',
        message: 'Error on get contact by PN-LID',
        error: error,
      });
    }
  }
}
