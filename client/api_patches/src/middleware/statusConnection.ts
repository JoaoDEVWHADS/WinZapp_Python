/*
 * Copyright 2021 WPPConnect Team
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { NextFunction, Request, Response } from 'express';

import { SessionNotReadyError } from '../errors/domain';
import { contactToArray } from '../util/functions';

function disconnected(res: Response) {
  return res.status(404).json({
    response: null,
    status: 'Disconnected',
    message: 'A sessão do WhatsApp não está ativa.',
  });
}

export default async function statusConnection(
  req: Request,
  res: Response,
  next: NextFunction
) {
  try {
    const numbers: any = [];
    if (req.client && req.client.isConnected) {
      const skipsConnectionProbe =
        req.path.endsWith('/typing') ||
        req.path.endsWith('/recording') ||
        req.path.endsWith('/send-seen');
      if (!skipsConnectionProbe) {
        const connected = await req.client.isConnected();
        if (connected !== true) return disconnected(res);
      }

      const localArr = contactToArray(
        req.body.phone || [],
        req.body.isGroup,
        req.body.isNewsletter,
        req.body.isLid
      );
      let index = 0;
      // Same multipart-string-truthiness pitfall as contactToArray()
      // (util/functions.ts) — req.body.isGroup arrives as the literal
      // string "false" for any multipart/form-data call, which is truthy
      // in a bare `||` check.
      const wantsGroup =
        req.body.isGroup === true || req.body.isGroup === 'true';
      const wantsNewsletter =
        req.body.isNewsletter === true || req.body.isNewsletter === 'true';
      const wantsLid = req.body.isLid === true || req.body.isLid === 'true';
      for (const contact of localArr) {
        if (
          wantsGroup ||
          wantsNewsletter ||
          wantsLid ||
          (typeof contact === 'string' && contact.endsWith('@lid')) ||
          req.path.endsWith('/typing') ||
          req.path.endsWith('/recording') ||
          req.path.endsWith('/send-seen')
        ) {
          // checkNumberStatus() below expects a phone-number JID it can look
          // up in WhatsApp's contact directory — it doesn't understand @lid
          // identifiers. When the caller explicitly says this is a @lid
          // contact (already resolved via our own lid<->phone cache), skip
          // the existence check instead of letting it wrongly report the
          // contact as nonexistent.
          localArr[index] = contact;
        } else if (numbers.indexOf(contact) < 0) {
          console.log(contact);
          const profile: any = await req.client
            .checkNumberStatus(contact)
            .catch((error) => console.log(error));
          if (!profile?.numberExists) {
            const num = (contact as any).split('@')[0];
            return res.status(400).json({
              response: null,
              status: 'Connected',
              message: `O número ${num} não existe.`,
            });
          } else {
            if ((numbers as any).indexOf(profile.id._serialized) < 0) {
              (numbers as any).push(profile.id._serialized);
            }
            (localArr as any)[index] = profile.id._serialized;
          }
        }
        index++;
      }
      req.body.phone = localArr;
    } else {
      return disconnected(res);
    }
    next();
  } catch (error) {
    const detail = String((error as any)?.message || error || '');
    if (/WAPI is not defined|Execution context was destroyed/i.test(detail)) {
      next(new SessionNotReadyError(detail));
      return;
    }
    if (/Target closed|not connected|Session (closed|not active)/i.test(detail)) {
      disconnected(res);
      return;
    }
    next(error);
  }
}
