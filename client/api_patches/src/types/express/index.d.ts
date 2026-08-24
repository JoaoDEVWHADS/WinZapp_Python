import { Whatsapp } from '@wppconnect-team/wppconnect';
import { Server as Socket } from 'socket.io';
import { Logger } from 'winston';

import { ServerOptions } from '../ServerOptions';

// to make the file a module and avoid the TypeScript error
export {};

declare global {
  namespace Express {
    export interface Request {
      client: Whatsapp & { urlcode: string; status: string };
      logger: Logger;
      requestId: string;
      session: string;
      token?: string;
      io: Socket;
      serverOptions: ServerOptions;
    }
  }
}
