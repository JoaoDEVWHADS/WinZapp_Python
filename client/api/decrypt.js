"use strict";
/*
 * This file is part of WPPConnect.
 *
 * WPPConnect is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Lesser General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * WPPConnect is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with WPPConnect.  If not, see <https://www.gnu.org/licenses/>.
 */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.newMagix = exports.magix = exports.mediaTypes = exports.timeout = exports.makeOptions = void 0;
const crypto = __importStar(require("crypto"));
const futoin_hkdf_1 = __importDefault(require("futoin-hkdf"));
const atob_1 = __importDefault(require("atob"));
const stream_1 = require("stream");
const makeOptions = (useragentOverride, responseType = 'arraybuffer') => ({
    responseType: responseType,
    headers: {
        'User-Agent': processUA(useragentOverride),
        DNT: '1',
        'Upgrade-Insecure-Requests': '1',
        origin: 'https://web.whatsapp.com/',
        referer: 'https://web.whatsapp.com/',
    },
});
exports.makeOptions = makeOptions;
const timeout = (ms) => new Promise((res) => setTimeout(res, ms));
exports.timeout = timeout;
exports.mediaTypes = {
    IMAGE: 'Image',
    VIDEO: 'Video',
    AUDIO: 'Audio',
    PTT: 'Audio',
    DOCUMENT: 'Document',
    STICKER: 'Image',
};
const processUA = (userAgent) => {
    let ua = userAgent ||
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.5005.63 Safari/537.36';
    if (!ua.includes('WhatsApp'))
        ua = 'WhatsApp/2.16.352 ' + ua;
    return ua;
};
const magix = (fileData, mediaKeyBase64, mediaType, expectedSize) => {
    const encodedBytes = new Uint8Array(fileData);
    const mediaKeyBytes = base64ToBytes(mediaKeyBase64);
    const info = `WhatsApp ${exports.mediaTypes[mediaType.toUpperCase()]} Keys`;
    const hash = 'sha256';
    const salt = new Uint8Array(32);
    const expandedSize = 112;
    const mediaKeyExpanded = (0, futoin_hkdf_1.default)(mediaKeyBytes, expandedSize, {
        salt,
        info,
        hash,
    });
    const iv = mediaKeyExpanded.slice(0, 16);
    const cipherKey = mediaKeyExpanded.slice(16, 48);
    const decipher = crypto.createDecipheriv('aes-256-cbc', cipherKey, iv);
    const decoded = decipher.update(encodedBytes);
    const mediaDataBuffer = expectedSize
        ? fixPadding(decoded, expectedSize)
        : decoded;
    return mediaDataBuffer;
};
exports.magix = magix;
const fixPadding = (data, expectedSize) => {
    let padding = (16 - (expectedSize % 16)) & 0xf;
    if (padding > 0) {
        if (expectedSize + padding == data.length) {
            //  console.log(`trimmed: ${padding} bytes`);
            data = data.slice(0, data.length - padding);
        }
        else if (data.length + padding == expectedSize) {
            // console.log(`adding: ${padding} bytes`);
            let arr = new Uint16Array(padding).map((b) => padding);
            data = Buffer.concat([data, Buffer.from(arr)]);
        }
    }
    //@ts-ignore
    return Buffer.from(data, 'utf-8');
};
const hexToBytes = (hexStr) => {
    const intArray = [];
    for (let i = 0; i < hexStr.length; i += 2) {
        intArray.push(parseInt(hexStr.substr(i, 2), 16));
    }
    return new Uint8Array(intArray);
};
const base64ToBytes = (base64Str) => {
    const binaryStr = (0, atob_1.default)(base64Str);
    const byteArray = new Uint8Array(binaryStr.length);
    for (let i = 0; i < binaryStr.length; i++) {
        byteArray[i] = binaryStr.charCodeAt(i);
    }
    return byteArray;
};
const newMagix = (mediaKeyBase64, mediaType, expectedSize) => {
    const mediaKeyBytes = newBase64ToBytes(mediaKeyBase64);
    const info = `WhatsApp ${exports.mediaTypes[mediaType.toUpperCase()]} Keys`;
    const hash = 'sha256';
    const salt = Buffer.alloc(32);
    const expandedSize = 112;
    const mediaKeyExpanded = (0, futoin_hkdf_1.default)(mediaKeyBytes, expandedSize, {
        salt,
        info,
        hash,
    });
    const iv = mediaKeyExpanded.slice(0, 16);
    const cipherKey = mediaKeyExpanded.slice(16, 48);
    const decipher = crypto.createDecipheriv('aes-256-cbc', cipherKey, iv);
    let processedBytes = 0;
    let buffer = Buffer.alloc(0);
    const transformStream = new stream_1.Transform({
        transform(chunk, encoding, callback) {
            try {
                const decryptedChunk = decipher.update(chunk);
                processedBytes += decryptedChunk.length;
                if (processedBytes > expectedSize) {
                    const paddedChunk = Buffer.from(decryptedChunk).slice(0, buffer.length - (processedBytes - expectedSize));
                    callback(null, paddedChunk);
                }
                else {
                    callback(null, decryptedChunk);
                }
            }
            catch (error) {
                callback(error);
            }
        },
    });
    transformStream.on('error', (error) => {
        console.error('Error during decryption:', error);
    });
    return transformStream;
};
exports.newMagix = newMagix;
const newBase64ToBytes = (base64Str) => Buffer.from(base64Str, 'base64');
