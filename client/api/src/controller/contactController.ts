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
      const response = await req.client.getPnLidEntry(pnLid) as any;
      const pnJid = response?.contact?.id?._serialized || response?.contact?.id || null;
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
