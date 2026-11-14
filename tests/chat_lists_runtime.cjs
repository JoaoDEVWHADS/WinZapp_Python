// Execute the actual self-contained page function on synthetic WhatsApp stores.
// No browser, API process, npm install or user profile is involved.
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8').replace('export async function', 'async function');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const calls = [];
const labels = new Map((input.lists || []).map(item => [item.id, { ...item, type: item.type ?? 5 }]));
const chats = (input.chats || []).map(chat => ({ id: { _serialized: chat.id }, labels: [...chat.labels] }));
let nextId = 100;
const runtime = {
  whatsapp: {
    ChatStore: { getModelsArray: () => chats },
    LabelStore: { get: id => labels.get(id) },
    labelsEditingEnabled: () => input.editable !== false,
  },
  lists: {
    list: () => [...labels.values()],
    create: async name => { const id = String(nextId++); calls.push(['create', name]); labels.set(id, { id, name, type: 5 }); return id; },
    rename: async (id, name) => { calls.push(['rename', id, name]); labels.get(id).name = name; },
    remove: async id => { calls.push(['remove', id]); labels.delete(id); },
    addChats: async (id, ids) => { calls.push(['addChats', id, ids]); for (const chat of chats) if (ids.includes(chat.id._serialized)) chat.labels.push(id); },
    removeChats: async (id, ids) => { calls.push(['removeChats', id, ids]); for (const chat of chats) if (ids.includes(chat.id._serialized)) chat.labels = chat.labels.filter(label => label !== id); },
  },
};
if (input.missing) delete runtime[input.missing];
if (input.missingMethod) delete runtime.lists[input.missingMethod];
if (input.capabilityMode === 'missing') delete runtime.whatsapp.labelsEditingEnabled;
if (input.capabilityMode === 'throws') runtime.whatsapp.labelsEditingEnabled = () => { throw new Error('private native details'); };
if (input.capabilityMode === 'invalid') runtime.whatsapp.labelsEditingEnabled = () => 'true';
if (input.capabilityMode === 'not_function') runtime.whatsapp.labelsEditingEnabled = false;
if (input.modern) {
  const modules = {
    WAWebBizLabelEditingAction: {
      async labelAddAction(name, color) {
        calls.push(['nativeCreate', name, color]);
        if (input.nativeThrows) throw new Error('private native details');
        if (input.nativeEmptyId) return undefined;
        const id = nextId++;
        labels.set(String(id), {id: String(id), name, type: 5, colorIndex: color, isActive: true});
        return id;
      },
      async labelEditAction(id, name, predefinedId, color, isActive, type) {
        calls.push(['nativeRename', id, name, predefinedId, color, isActive, type]);
        if (input.nativeThrows) throw new Error('private native details');
        labels.get(id).name = name;
      },
      async labelDeleteAction(options) {
        calls.push(['nativeRemove', options]);
        if (input.nativeThrows) throw new Error('private native details');
        labels.delete(options.labelId);
      },
    },
    WAWebListsActions: {createNewListAction() {}, editListAction() {}, deleteListAction() {}},
    WAWebMobilePlatforms: {isSMB: () => input.business === true},
    WAWebInboxFiltersGatingUtils: {inboxFiltersEnabled: () => input.filters ?? true},
    // These unrelated flags are false in the reported session.
    WAWebListsLabelGatingUtils: {smartFiltersEnabled: () => false},
  };
  runtime.version = input.version ?? '4.6.1';
  runtime.isReady = input.ready ?? true;
  runtime.loader = {loaderType: input.loaderType ?? 'meta', loadModule(id) {
    if (input.moduleThrows) throw new Error('private native details');
    return id === input.missingModule ? null : modules[id];
  }};
  if (input.missingNativeAction) delete modules.WAWebBizLabelEditingAction[input.missingNativeAction];
  if (input.wrongNativeArity) modules.WAWebBizLabelEditingAction.labelDeleteAction = async (id, name, color) => {calls.push(['wrong', id]);};
  if (input.legacyNativeGate) modules.WAWebListsLabelGatingUtils.labelsEditingEnabled = () => false;
}
const context = vm.createContext({ WPP: runtime });
vm.runInContext(source, context);
const execute = context.executeListCommand;
(async () => {
  const results = [];
  for (const command of input.commands || []) {
    try { results.push({ value: await execute(command) }); }
    catch (error) { results.push({ error: error.code || error.message }); }
  }
  process.stdout.write(JSON.stringify({ results, calls }));
})().catch(error => { process.stderr.write(String(error)); process.exitCode = 1; });
