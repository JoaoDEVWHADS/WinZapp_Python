"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.logger = void 0;
exports.initServer = initServer;

let wppconnect_1 = null;
try { wppconnect_1 = require("@wppconnect-team/wppconnect"); } catch (e) {}

let cors_1 = null;
try { cors_1 = __importDefault(require("cors")); } catch (e) {}

let express_1 = null;
try { express_1 = __importDefault(require("express")); } catch (e) {}

let express_query_boolean_1 = null;
try { express_query_boolean_1 = __importDefault(require("express-query-boolean")); } catch (e) {}

let http_1 = null;
try { http_1 = require("http"); } catch (e) {}

let merge_deep_1 = null;
try {
    merge_deep_1 = __importDefault(require("merge-deep"));
} catch (e) {
    merge_deep_1 = { default: (target, ...sources) => Object.assign(target || {}, ...sources) };
}

let process_1 = __importDefault(require("process"));
let socket_io_1 = null;
try { socket_io_1 = require("socket.io"); } catch (e) {}

let createLoggerFn = function () {
    return {
        info: console.log,
        error: console.error,
        warn: console.warn,
        debug: console.log,
        silly: console.log
    };
};
try {
    const loggerMod = require('./util/logger');
    if (loggerMod && typeof loggerMod.createLogger === 'function') {
        createLoggerFn = loggerMod.createLogger;
    }
} catch (e) {}

const version = "2.10.0";
const defaultConfig = {
    port: 6300,
    host: 'http://127.0.0.1',
    log: { level: 'silly', logger: ['console', 'file'] }
};

exports.logger = createLoggerFn(defaultConfig.log);

function initServer(serverOptions) {
    if (!express_1 || typeof express_1.default !== 'function') {
        console.error("[dist/index.js] express module is not installed in node_modules yet. Please run: python setup_api.py");
        return null;
    }

    if (typeof serverOptions !== 'object') {
        serverOptions = {};
    }
    const mergeFn = merge_deep_1?.default || Object.assign;
    serverOptions = mergeFn({}, defaultConfig, serverOptions);
    if (wppconnect_1 && wppconnect_1.defaultLogger) {
        wppconnect_1.defaultLogger.level = serverOptions?.log?.level ? serverOptions.log.level : 'silly';
    }

    const app = (0, express_1.default)();
    const PORT = process_1.default.env.PORT || serverOptions.port || 6300;

    if (cors_1 && typeof cors_1.default === 'function') {
        app.use((0, cors_1.default)());
    }
    app.use(express_1.default.json({ limit: '50mb' }));
    app.use(express_1.default.urlencoded({ limit: '50mb', extended: true }));
    app.use('/files', express_1.default.static('WhatsAppImages'));
    if (express_query_boolean_1 && typeof express_query_boolean_1.default === 'function') {
        app.use((0, express_query_boolean_1.default)());
    }

    const createHttpServer = http_1?.createServer || require('http').createServer;
    const http = createHttpServer(app);
    let io = null;
    if (socket_io_1 && socket_io_1.Server) {
        io = new socket_io_1.Server(http, { cors: { origin: '*' } });
        io.on('connection', (sock) => {
            exports.logger.info(`ID: ${sock.id} entrou`);
            sock.on('disconnect', () => {
                exports.logger.info(`ID: ${sock.id} saiu`);
            });
        });
    }

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

    // Tenta carregar as rotas reais do WPPConnect compiladas pelo Babel
    let routesLoaded = false;
    const routePaths = ['./routes/index', './routes', '../src/routes/index', '../src/routes'];
    for (const rPath of routePaths) {
        try {
            const routesModule = require(rPath);
            const routesObj = routesModule?.default || routesModule;
            if (routesObj && (typeof routesObj === 'function' || typeof routesObj.use === 'function')) {
                app.use(routesObj);
                routesLoaded = true;
                exports.logger.info(`[initServer] Successfully mounted API routes from ${rPath}`);
                break;
            }
        } catch (e) {}
    }

    if (!routesLoaded) {
        exports.logger.warn(`[initServer] Could not find compiled routes module in dist/routes. Run: python setup_api.py`);
    }

    app.get('/status', (req, res) => {
        res.json({ status: 'ONLINE', version: version });
    });

    http.listen(PORT, () => {
        exports.logger.info(`Server is running on port: ${PORT}`);
        exports.logger.info(`Visit ${serverOptions.host || 'http://127.0.0.1'}:${PORT}/api-docs for Swagger docs`);
        exports.logger.info(`WPPConnect-Server version: ${version}`);
    });

    return { app, logger: exports.logger };
}
