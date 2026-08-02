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
const config_1 = __importDefault(require("./config"));
const index_1 = require("./mapper/index");
const routes_1 = __importDefault(require("./routes"));
const functions_1 = require("./util/functions");
const logger_1 = require("./util/logger");

const version = "2.10.0";
exports.logger = (0, logger_1.createLogger)(config_1.default.log);

function initServer(serverOptions) {
    if (typeof serverOptions !== 'object') {
        serverOptions = {};
    }
    serverOptions = (0, merge_deep_1.default)({}, config_1.default, serverOptions);
    wppconnect_1.defaultLogger.level = serverOptions?.log?.level ? serverOptions.log.level : 'silly';
    (0, functions_1.setMaxListners)(serverOptions);

    const app = (0, express_1.default)();
    const PORT = process_1.default.env.PORT || serverOptions.port || 6300;

    app.use((0, cors_1.default)());
    app.use(express_1.default.json({ limit: '50mb' }));
    app.use(express_1.default.urlencoded({ limit: '50mb', extended: true }));
    app.use('/files', express_1.default.static('WhatsAppImages'));
    app.use((0, express_query_boolean_1.default)());

    if (config_1.default?.aws_s3?.access_key_id && config_1.default?.aws_s3?.secret_key) {
        process_1.default.env['AWS_ACCESS_KEY_ID'] = config_1.default.aws_s3.access_key_id;
        process_1.default.env['AWS_SECRET_ACCESS_KEY'] = config_1.default.aws_s3.secret_key;
    }

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
                        if (data.mapper && req.serverOptions.mapper.enable) {
                            data.response = await (0, index_1.convert)(req.serverOptions.mapper.prefix, data.response, data.mapper);
                            delete data.mapper;
                        }
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

    app.use(routes_1.default);
    (0, functions_1.createFolders)();

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
        if (serverOptions.startAllSession) {
            (0, functions_1.startAllSessions)(serverOptions, exports.logger);
        }
    });

    return { app, routes: routes_1.default, logger: exports.logger };
}
