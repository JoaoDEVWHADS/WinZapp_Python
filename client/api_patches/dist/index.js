"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.logger = void 0;
exports.initServer = initServer;
const wppconnect_1 = require("@wppconnect-team/wppconnect");
const cors_1 = __importDefault(require("cors"));
const express_1 = __importDefault(require("express"));
const express_query_boolean_1 = __importDefault(require("express-query-boolean"));
const http_1 = require("http");
const merge_deep_1 = __importDefault(require("merge-deep"));
const process_1 = __importDefault(require("process"));
const socket_io_1 = require("socket.io");
const path_1 = __importDefault(require("path"));

// Tenta carregar config e logger locais, ou usa fallbacks seguros
let createLoggerFn;
try {
    createLoggerFn = require('./util/logger').createLogger;
} catch (e) {
    createLoggerFn = function () {
        return {
            info: console.log,
            error: console.error,
            warn: console.warn,
            debug: console.log,
            silly: console.log
        };
    };
}

const version = "2.10.0";
const defaultConfig = {
    port: 6300,
    host: 'http://127.0.0.1',
    log: { level: 'silly', logger: ['console', 'file'] }
};

exports.logger = createLoggerFn(defaultConfig.log);

function initServer(serverOptions) {
    if (typeof serverOptions !== 'object') {
        serverOptions = {};
    }
    serverOptions = (0, merge_deep_1.default)({}, defaultConfig, serverOptions);
    wppconnect_1.defaultLogger.level = serverOptions?.log?.level ? serverOptions.log.level : 'silly';

    const app = (0, express_1.default)();
    const PORT = process_1.default.env.PORT || serverOptions.port || 6300;

    app.use((0, cors_1.default)());
    app.use(express_1.default.json({ limit: '50mb' }));
    app.use(express_1.default.urlencoded({ limit: '50mb', extended: true }));
    app.use('/files', express_1.default.static('WhatsAppImages'));
    app.use((0, express_query_boolean_1.default)());

    const http = (0, http_1.createServer)(app);
    const io = new socket_io_1.Server(http, {
        cors: { origin: '*' }
    });

    app.use((req, res, next) => {
        req.serverOptions = serverOptions;
        req.logger = exports.logger;
        req.io = io;
        const oldSend = res.send;
        res.send = async function (data) {
            const content = req.headers['content-type'];
            if (content == 'application/json' && data && typeof data === 'string') {
                try {
                    const parsed = JSON.parse(data);
                    if (parsed && typeof parsed === 'object') {
                        data = parsed;
                        if (!data.session) data.session = req.client ? req.client.session : '';
                    }
                } catch (e) {
                    req.logger.error(`[res.send interceptor] Error parsing JSON: ${e}`);
                }
            }
            res.send = oldSend;
            return res.send(data);
        };
        next();
    });

    // Carrega as rotas da API se disponíveis
    try {
        let routesModule = null;
        try {
            routesModule = require('./routes');
        } catch (e1) {
            try {
                routesModule = require('../src/routes');
            } catch (e2) {}
        }
        if (routesModule) {
            const routesObj = routesModule.default || routesModule;
            app.use(routesObj);
        }
    } catch (e) {
        exports.logger.error(`[initServer] Could not load routes: ${e}`);
    }

    // Rota de status básica de fallback
    app.get('/status', (req, res) => {
        res.json({ status: 'ONLINE', version: version });
    });

    io.on('connection', (sock) => {
        exports.logger.info(`ID: ${sock.id} entrou`);
        sock.on('disconnect', () => {
            exports.logger.info(`ID: ${sock.id} saiu`);
        });
    });

    http.listen(PORT, () => {
        exports.logger.info(`Server is running on port: ${PORT}`);
        exports.logger.info(`Visit ${serverOptions.host || 'http://127.0.0.1'}:${PORT}/api-docs for Swagger docs`);
        exports.logger.info(`WPPConnect-Server version: ${version}`);
    });

    return { app, logger: exports.logger };
}
