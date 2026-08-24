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

import { classifyPageError, DomainError } from '../errors/domain';

/**
 * WinZapp patch: the one place a failure becomes an HTTP response.
 *
 * Business logic throws a DomainError saying what went wrong; this decides
 * what that means over the wire. Keeping the two apart is what lets a service
 * be tested without a web framework, and what stops the next endpoint from
 * inventing its own status for "chat not found".
 *
 * Registered AFTER the routes (Express only treats a four-argument function as
 * an error handler, and only consults it once everything before it has passed
 * the error along).
 */
export function errorHandler(
  error: any,
  req: Request,
  res: Response,
  next: NextFunction
): void {
  // Express's contract: once a response has started, the error cannot be
  // turned into a body any more — handing it back is the only correct move.
  if (res.headersSent) {
    next(error);
    return;
  }

  const domain: DomainError =
    error instanceof DomainError ? error : classifyPageError(error);

  const logger: any = (req as any).logger || console;
  const line =
    `[${domain.reason}] ${req.method} ${req.originalUrl?.split('?')[0]} ` +
    `-> ${domain.httpStatus}: ${domain.message}`;
  // A 5xx is ours to fix and gets the stack; a 4xx is the caller being told
  // something true about their request, and logging a stack for each one
  // buries the ones that matter.
  if (domain.httpStatus >= 500) {
    logger.error?.(`${line}\n${error?.stack || ''}`);
  } else {
    logger.warn?.(line);
  }

  res.status(domain.httpStatus).json({
    status: 'error',
    reason: domain.reason,
    message: domain.message,
    ...(Object.keys(domain.details).length ? { details: domain.details } : {}),
  });
}
