import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const V2 = {
    GreymonkeyPromptGenerator: "GreymonkeyPromptGeneratorV2",
    GreymonkeySceneSubject: "GreymonkeySceneSubjectV2",
    GreymonkeyCameraStyle: "GreymonkeyCameraStyleV2",
    GreymonkeySaveImage: "GreymonkeySaveImageV2",
};
const subjectClasses = new Set(["GreymonkeySceneSubject", "GreymonkeySceneSubjectV2"]);
const personNames = ["gender", "ethnicity", "hair_color", "hair_length", "magic", "subject_style"];
const detailNames = ["identity", "detail_1", "detail_2", "detail_3", "detail_4", ...personNames];
let refreshPromise;

function toast(message, severity = "warn") {
    app.extensionManager.toast.add({severity, summary: "Greymonkey", detail: String(message), life: 10000});
}
function id(value) { return String(value).split("[").pop().replace(/\]$/, ""); }
// ComfyUI can wrap workflow state in reactive proxies, which structuredClone rejects.
// Persisted workflows are JSON data; copy that representation without retaining proxies.
function clonePersistedData(value) {
    return JSON.parse(JSON.stringify(value));
}
function savedWidgets(node) {
    return Object.fromEntries((node.widgets || []).filter(w => w.options?.serialize !== false && ["string", "number", "boolean"].includes(typeof w.value)).map(w => [w.name, w.value]));
}
function choices(widget, values) {
    // Retain a missing saved entry explicitly; never substitute Random on reload.
    widget.options ||= {};
    widget.options.values = values.includes(widget.value) ? values : [...values, widget.value];
}
function hidden(widget, hide) {
    if (!widget) return;
    if (!widget.greymonkeyOriginal) widget.greymonkeyOriginal = {type: widget.type, computeSize: widget.computeSize};
    widget.hidden = hide;
    widget.type = hide ? "greymonkey-hidden" : widget.greymonkeyOriginal.type;
    widget.computeSize = hide ? () => [0, -4] : widget.greymonkeyOriginal.computeSize;
    if (widget.element) widget.element.style.display = hide ? "none" : "";
}
function resize(node) {
    if (node.computeSize) node.setSize([Math.max(node.size[0], 340), node.computeSize()[1]]);
    app.graph?.setDirtyCanvas(true, true);
}
function filterRelationships(node) {
    const related=node.widgets.find(w=>w.name==="related_object" || node.comfyClass==="GreymonkeySceneObjectV2" && w.name==="identity");
    const relationship=node.widgets.find(w=>w.name==="relationship");
    if(!related||!relationship)return;
    relationship.options ||= {};
    relationship.options.greymonkeyAllRelationships ||= [...(relationship.options.values||[])];
    const all=relationship.options.greymonkeyAllRelationships;
    const selected=String(related.value), entry=related.options?.greymonkeyEntries?.find(e=>e.id===id(selected));
    const name=(entry?.name||selected).toLowerCase();
    let allowed=["none","next_to","in_front_of","behind","looking_at"];
    if(["None","none"].includes(selected))allowed.push("kissing");
    else if(["Random","random"].includes(selected))allowed=all;
    else if(name.includes("microphone"))allowed.push("speaking_into","singing_into","recording_with","holding","holding_near_face","holding_at_chest","holding_two_handed","holding_left_hand","holding_right_hand","holding_delicately","holding_at_arm_length");
    else if(entry?.capabilities?.object_kind==="vehicle"||/vehicle_type_|drift build|cars & vehicles/.test(name))allowed.push("leaning_against","inside","sitting_driver","sitting_passenger","driving","entering","exiting","sitting_hood");
    else {
        allowed.push("holding","holding_near_face","holding_at_chest","holding_two_handed","holding_left_hand","holding_right_hand","holding_delicately","holding_on_palm","holding_at_arm_length","throwing");
        if(/book|magazine|newspaper/.test(name))allowed.push("reading");
        if(/mug|cup|bottle|glass/.test(name))allowed.push("drinking_from");
    }
    choices(relationship,all.filter(value=>allowed.includes(value)));
}
function filterSubject(node) {
    filterRelationships(node);
    const type = node.widgets.find(w => w.name === "subject_type")?.value;
    if (!type) return;
    for (const name of ["identity", "detail_1", "detail_2", "detail_3", "detail_4"]) {
        const widget = node.widgets.find(w => w.name === name);
        const entries = widget?.options?.greymonkeyEntries;
        if (!entries) continue;
        choices(widget, ["Random", ...entries.filter(e => (e.types || [e.type]).includes(type)).map(e => `${e.name} [${e.id}]`)]);
    }
    for (const name of personNames) hidden(node.widgets.find(w => w.name === name), type !== "person");
    resize(node);
}
function connectedModels(node) {
    const queue=[node],seen=new Set(),models=[];
    while(queue.length){
        const current=queue.shift();if(!current||seen.has(current.id))continue;seen.add(current.id);
        const model=current.widgets?.find(w=>w.name==="model_id");if(model)models.push(model.value);
        for(const output of current.outputs||[])for(const linkId of output.links||[]){
            const link=app.graph.links?.[linkId];
            if(link)queue.push(app.graph.getNodeById(link.target_id));
        }
    }
    return models;
}
function filterDetail(node) {
    const category = node.widgets.find(w => w.name === "category")?.value;
    const option = node.widgets.find(w => w.name === "option");
    const entries = (option?.options?.greymonkeyEntries || []).filter(e=>node.comfyClass!=="GreymonkeyObjectDetailV2" || (e.types||[e.type]).includes("product") && e.slot!=="object_identity");
    if (option) choices(option, [...(node.comfyClass === "GreymonkeyEnvironmentDetailV2" ? [] : ["Random"]), ...entries.filter(e => (e.category_id || e.category) === id(category) || e.category === category).map(e => `${e.name} [${e.id}]`)]);
    const entry = entries.find(e => e.id === id(option?.value));
    hidden(node.widgets.find(w => w.name === "color"), !entry?.colorable);
    const weight=node.widgets.find(w=>w.name==="weight"),models=connectedModels(node);
    if(weight){
        const supported=models.some(id=>(weight.options.greymonkeyWeightModels||[]).includes(id));
        hidden(weight,!supported&&Number(weight.value)===1);
        weight.label=supported?"Weight":"Weight (saved; inactive for connected model)";
    }
    resize(node);
}
function filterRandom(node) {
    const type = node.widgets.find(w => w.name === "scene_type")?.value;
    hidden(node.widgets.find(w => w.name === "subject_count"), !["person", "animal", "product"].includes(type));
    hidden(node.widgets.find(w => w.name === "species_pool"), type !== "person");
    resize(node);
}
function restore(node, values) {
    for (const widget of node.widgets || []) {
        if (!Object.prototype.hasOwnProperty.call(values, widget.name)) continue;
        const value = values[widget.name];
        if (!["string", "number", "boolean"].includes(typeof value)) continue;
        if (Array.isArray(widget.options?.values)) choices(widget, [...widget.options.values, value]);
        widget.value = value;
    }
}
function textPreview(node, name, value, height = 100) {
    let widget = node.widgets.find(w => w.name === name);
    if (!widget) {
        const element = document.createElement("textarea");
        element.readOnly = true;
        element.setAttribute("aria-label", name);
        element.style.cssText = `width:100%;height:${height}px;resize:vertical;box-sizing:border-box;`;
        widget = node.addDOMWidget(name, "text", element, {serialize: false});
    }
    widget.element.value = String(value ?? "");
}

async function refreshAll() {
    if (refreshPromise) return refreshPromise;
    refreshPromise = (async () => {
        const response = await api.fetchApi("/greymonkey/models/refresh", {method: "POST"});
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || "Catalog refresh failed");
        for (const node of app.graph._nodes || []) {
            if (!String(node.comfyClass || node.type).startsWith("Greymonkey")) continue;
            for (const widget of node.widgets || []) {
                let entries, defaults = ["Random"];
                if ((node.comfyClass || node.type) === "GreymonkeyInfluencerSettingsV2") {
                    const values = data.creator_catalog?.choices?.[widget.name];
                    if (Array.isArray(values)) choices(widget, values);
                    continue;
                }
                if(widget.name === "weight") {
                    widget.options.greymonkeyWeightModels = data.models.filter(m => ((m.capabilities || m.prompt_capabilities || {}).weight_workflows || []).includes("comfyui")).map(m=>m.id);
                    continue;
                }
                if (widget.name === "model_id") {
                    choices(widget, data.models.filter(m => m.comfyui !== false).map(m => m.id)); continue;
                }
                if (widget.name === "art_style") entries = data.art_styles;
                const group = {location:"locations", time_of_day:"times", identity:"identities", related_object:"identities", magic:"magic", ethnicity:"ethnicities", hair_color:"hair_colors", hair_length:"hair_lengths", option:"details", detail_1:"details", detail_2:"details", detail_3:"details", detail_4:"details"}[widget.name];
                if (group) entries = data.controls?.[group];
                if (node.comfyClass === "GreymonkeyEnvironmentDetailV2" && widget.name === "option") entries = (data.controls?.global_details || []).filter(e => !["location", "time_of_day"].includes(e.slot));
                if (widget.name === "category") {
                    choices(widget, [...new Set((node.comfyClass === "GreymonkeyEnvironmentDetailV2" ? (data.controls?.global_details || []).filter(e => !["location", "time_of_day"].includes(e.slot)) : (data.controls?.details || [])).map(e => `${e.category || "Other"} [${e.category_id || e.category || "Other"}]`))].sort()); continue;
                }
                if (!Array.isArray(entries)) continue;
                if (["related_object", "magic"].includes(widget.name)) defaults = ["None", "Random"];
                if (widget.name === "related_object" || node.comfyClass === "GreymonkeySceneObjectV2" && widget.name === "identity") entries = entries.filter(e => e.type === "product");
                if (node.comfyClass === "GreymonkeyObjectDetailV2") entries = entries.filter(e => (e.types || [e.type]).includes("product") && e.slot !== "object_identity");
                widget.options.greymonkeyEntries = entries;
                choices(widget, [...defaults, ...entries.map(e => `${e.name} [${e.id}]`)]);
            }
            node.greymonkeyFilter?.();
        }
        toast("Catalog refreshed. Existing selections were retained.", "success");
    })().finally(() => { refreshPromise = null; });
    return refreshPromise;
}

function legacyValues(node, data) {
    if (data.properties?.greymonkey_state?.values) return data.properties.greymonkey_state.values;
    if (data.properties?.greymonkey_widget_state) return data.properties.greymonkey_widget_state;
    const values = data.widgets_values;
    if (!Array.isArray(values)) return null;
    const type = node.comfyClass || node.type;
    if (type === "GreymonkeyPromptGenerator") {
        const prefix = ["model_id", "scene_type", "subject_count", "content_mode"];
        const hasPool = ["All supported humanoid races", "Humans only", "Non-human humanoids only"].includes(values[4]);
        const middle = ["detail_level", "background", "pose_mode", "aspect_ratio", "quality", "seed", "control_after_generate"];
        const index = prefix.length + (hasPool ? 1 : 0) + middle.length;
        const hasGender = ["Random / varied", "Female / woman", "Male / man", "Nonbinary"].includes(values[index]);
        const names = [...prefix, ...(hasPool ? ["species_pool"] : []), ...middle, ...(hasGender ? ["gender", "hybrid_type"] : []), "art_style", "generation_theme"];
        if (values.length < names.length) return null;
        return Object.fromEntries(names.map((name, i) => [name, values[i]]));
    }
    // Other legacy layouts kept append-only widget order. Capture their loaded names.
    if (Object.hasOwn(V2, type)) return savedWidgets(node);
    return null;
}

function download(name, value) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: "application/json"}));
    const link = document.createElement("a"); link.href = url; link.download = name; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function dialog(title, message, proceed) {
    const box = document.createElement("dialog");
    const heading = document.createElement("h3"); heading.textContent = title;
    const text = document.createElement("pre"); text.textContent = message; text.style.cssText = "white-space:pre-wrap;max-height:60vh;overflow:auto";
    const cancel = document.createElement("button"); cancel.textContent = "Cancel"; cancel.onclick = () => box.close();
    box.append(heading, text, cancel);
    if (proceed) {
        const confirm = document.createElement("button"); confirm.textContent = "Download upgraded copy";
        confirm.onclick = () => { proceed(); box.close(); }; box.append(confirm);
    }
    box.addEventListener("close", () => box.remove()); document.body.append(box); box.showModal();
}
function upgradeWorkflow() {
    const workflow = clonePersistedData(app.graph.serialize());
    const errors = [], changes = [], extra = [], byId = new Map(workflow.nodes.map(n => [n.id,n]));
    let nextId = Math.max(0,...workflow.nodes.map(n => Number(n.id) || 0));
    let nextLink = Math.max(0,...(workflow.links || []).map(l => Number(l[0]) || 0));
    const Lite = globalThis.LiteGraph;
    function create(type, values, pos, nodeId = ++nextId) {
        const instance = Lite?.createNode(type);
        if (!instance) { errors.push(`Node definition ${type} is unavailable; restart after installing the update.`); return null; }
        restore(instance, values); const node = instance.serialize(); node.id = nodeId; node.pos = pos;
        node.properties ||= {}; node.properties.greymonkey_state = {version: 1, values: {...savedWidgets(instance)}, per_type: {}};
        for (const input of node.inputs || []) input.link = null;
        for (const output of node.outputs || []) output.links = [];
        return node;
    }
    function connect(source, outputName, target, inputName) {
        const out = source.outputs?.findIndex(o => o.name === outputName), input = target.inputs?.findIndex(i => i.name === inputName);
        if (out < 0 || input < 0 || out == null || input == null) { errors.push(`Cannot map ${outputName} to ${inputName}.`); return; }
        const link = ++nextLink; workflow.links.push([link,source.id,out,target.id,input,source.outputs[out].type]);
        (source.outputs[out].links ||= []).push(link); target.inputs[input].link = link;
    }
    const oldNodes = new Map(workflow.nodes.map(n => [n.id,clonePersistedData(n)]));
    for (let i = 0; i < workflow.nodes.length; i++) {
        const old = workflow.nodes[i]; if (!V2[old.type]) continue;
        const live = app.graph.getNodeById(old.id);
        const values = old.properties?.greymonkey_state?.values || old.properties?.greymonkey_widget_state;
        if (!values || live?.greymonkeyMigrationAmbiguous) { errors.push(`Node ${old.id}: reselect ambiguous legacy settings, save and reload before upgrading.`); continue; }
        const replacement = create(V2[old.type], values, old.pos, old.id); if (!replacement) continue;
        replacement.properties.greymonkey_state.per_type = old.properties?.greymonkey_state?.per_type || old.properties?.greymonkey_subject_type_values || {};
        workflow.nodes[i] = replacement; byId.set(old.id,replacement);
        changes.push(`${old.type} ${old.id} → ${replacement.type}`);
        if (old.type === "GreymonkeySceneSubject") {
            let previous = null;
            for (const name of ["detail_1","detail_2","detail_3","detail_4"]) {
                const value = values[name]; if (!value || ["Random","random"].includes(value)) continue;
                const optionWidget = Lite.createNode("GreymonkeySubjectDetailV2")?.widgets.find(w => w.name === "option");
                const entry = optionWidget?.options?.greymonkeyEntries?.find(e => e.id === id(value));
                if (!entry) { errors.push(`Subject ${old.id}: detail ${value} has no catalog mapping.`); continue; }
                const detail = create("GreymonkeySubjectDetailV2", {category:`${entry.category} [${entry.category_id || entry.category}]`,option:value}, [old.pos[0]-380,old.pos[1]+extra.length*70]);
                if (!detail) continue; extra.push(detail); byId.set(detail.id,detail);
                if (previous) connect(previous,"subject_details",detail,"previous_details"); previous=detail;
            }
            if (previous) connect(previous,"subject_details",replacement,"subject_details");
        }
        if (old.type === "GreymonkeyPromptGenerator" && !old.inputs?.some(i => i.name === "subjects" && i.link != null)) {
            const legacyPreferences = values.gender !== undefined || values.hybrid_type !== undefined;
            const random = create(legacyPreferences ? "GreymonkeyLegacyRandomSceneV2" : "GreymonkeyRandomSceneV2", {scene_type:values.scene_type || "person",subject_count:values.subject_count ?? 1,species_pool:values.species_pool || "All supported humanoid races",gender:values.gender || "Random / varied",hybrid_type:values.hybrid_type || "none"}, [old.pos[0]-380,old.pos[1]]);
            if (random) { extra.push(random); byId.set(random.id,random); connect(random,"scene",replacement,"scene"); }
        }
    }
    // Remap original edges by port name, never by shifted port number.
    const originalLinks = new Set((app.graph.serialize().links || []).map(l => l[0]));
    const portAliases = {subjects:"scene"};
    for (const link of workflow.links) {
        if (!originalLinks.has(link[0])) continue;
        const oldFrom=oldNodes.get(link[1]),oldTo=oldNodes.get(link[3]),from=byId.get(link[1]),to=byId.get(link[3]);
        const oldOutput=oldFrom?.outputs?.[link[2]]?.name,oldInput=oldTo?.inputs?.[link[4]]?.name;
        const outputName=V2[oldFrom?.type] ? (portAliases[oldOutput] || oldOutput) : oldOutput;
        const inputName=V2[oldTo?.type] ? (portAliases[oldInput] || oldInput) : oldInput;
        const oi=from?.outputs?.findIndex(p=>p.name===outputName),ii=to?.inputs?.findIndex(p=>p.name===inputName);
        if (oi == null || ii == null || oi<0 || ii<0) { errors.push(`Link ${link[0]} cannot be transferred safely.`); continue; }
        if (from.outputs[oi].type !== to.inputs[ii].type && from.outputs[oi].type !== "*" && to.inputs[ii].type !== "*") {
            errors.push(`Link ${link[0]} uses incompatible custom/legacy types; insert the Legacy Scene Adapter.`); continue;
        }
        link[2]=oi;link[4]=ii;link[5]=from.outputs[oi].type;
        from.outputs[oi].links ||= [];if (!from.outputs[oi].links.includes(link[0])) from.outputs[oi].links.push(link[0]);to.inputs[ii].link=link[0];
    }
    workflow.nodes.push(...extra);workflow.last_node_id=nextId;workflow.last_link_id=nextLink;
    const message = [...changes,...errors.map(e=>"BLOCKED: "+e),"","The current workflow stays untouched. An upgraded JSON copy is downloaded only after confirmation."].join("\n");
    dialog("Upgrade workflow preview", message, errors.length ? null : () => download("greymonkey-upgraded-workflow.json",workflow));
}

app.registerExtension({
    name: "Greymonkey.StableScenes",
    async beforeRegisterNodeDef(nodeType,nodeData) {
        if (!nodeData.name.startsWith("Greymonkey")) return;
        const created=nodeType.prototype.onNodeCreated,configured=nodeType.prototype.onConfigure,serialized=nodeType.prototype.onSerialize,executed=nodeType.prototype.onExecuted;
        nodeType.prototype.onNodeCreated=function() {
            const value=created?.apply(this,arguments);
            this.properties ||= {};
            for (const widget of this.widgets || []) {
                const schema = nodeData.input?.required?.[widget.name] || nodeData.input?.optional?.[widget.name];
                if (schema?.[1]?.greymonkeyWeightModels) {
                    widget.options ||= {};
                    widget.options.greymonkeyWeightModels = schema[1].greymonkeyWeightModels;
                }
                if (schema?.[1]?.greymonkeyEntries) {
                    widget.options ||= {};
                    widget.options.greymonkeyEntries = schema[1].greymonkeyEntries;
                }
            }
            const control=this.widgets?.find(w=>w.name==="control_after_generate");
            if(control)control.value="randomize";
            this.addWidget("button","Refresh catalog",null,()=>refreshAll().catch(e=>toast(e.message,"error")),{serialize:false});
            if(Object.hasOwn(V2,nodeData.name))this.addWidget("button","Upgrade workflow",null,upgradeWorkflow,{serialize:false});
            if(subjectClasses.has(nodeData.name)) {
                let active=this.widgets.find(w=>w.name==="subject_type")?.value;
                this.greymonkeyFilter=()=>filterSubject(this);
                const type=this.widgets.find(w=>w.name==="subject_type"),callback=type?.callback;
                if(type)type.callback=(value)=>{
                    callback?.call(type,value);
                    if(this.greymonkeyRestoring){active=value;return;}
                    const perType=(this.properties.greymonkey_state ||= {version:1,values:{},per_type:{}}).per_type ||= {};
                    if(value!==active){
                        perType[active]=Object.fromEntries(this.widgets.filter(w=>detailNames.includes(w.name)).map(w=>[w.name,w.value]));
                        const remembered=perType[value] || {};
                        for(const widget of this.widgets.filter(w=>detailNames.includes(w.name)))widget.value=remembered[widget.name] ?? (widget.name==="magic"?"None":widget.name==="subject_style"?"Default":widget.name==="gender"?"Random / varied":"Random");
                        active=value;
                    }
                    filterSubject(this);
                };
                const related=this.widgets.find(w=>w.name==="related_object"), relatedCallback=related?.callback;
                if(related)related.callback=(value)=>{relatedCallback?.call(related,value);filterRelationships(this);};
                this.greymonkeySetActiveType=()=>{active=type.value;};
            }
            if(nodeData.name==="GreymonkeySceneObjectV2") {
                this.greymonkeyFilter=()=>filterRelationships(this);
                const widget=this.widgets.find(w=>w.name==="identity"),callback=widget?.callback;
                if(widget)widget.callback=value=>{callback?.call(widget,value);filterRelationships(this);};
            }
            if(["GreymonkeySubjectDetailV2","GreymonkeyObjectDetailV2","GreymonkeyEnvironmentDetailV2"].includes(nodeData.name)) {
                this.greymonkeyFilter=()=>filterDetail(this);
                for(const name of ["category","option"]) {
                    const widget=this.widgets.find(w=>w.name===name),callback=widget?.callback;
                    if(widget)widget.callback=(value)=>{callback?.call(widget,value);if(!this.greymonkeyRestoring)filterDetail(this);};
                }
            }
            if(["GreymonkeyRandomSceneV2","GreymonkeyLegacyRandomSceneV2"].includes(nodeData.name)) {
                this.greymonkeyFilter=()=>filterRandom(this);
                const widget=this.widgets.find(w=>w.name==="scene_type"),callback=widget?.callback;
                if(widget)widget.callback=(value)=>{callback?.call(widget,value);filterRandom(this);};
            }
            if(nodeData.name.includes("PromptGenerator")){
                const model=this.widgets.find(w=>w.name==="model_id"),callback=model?.callback;
                if(model)model.callback=(value)=>{callback?.call(model,value);for(const node of app.graph._nodes||[])if(node.comfyClass==="GreymonkeySubjectDetailV2")node.greymonkeyFilter?.();};
            }
            const connected=this.onConnectionsChange;
            this.onConnectionsChange=function(){const result=connected?.apply(this,arguments);for(const node of app.graph._nodes||[])if(node.comfyClass==="GreymonkeySubjectDetailV2")node.greymonkeyFilter?.();return result;};
            this.greymonkeyFilter?.();return value;
        };
        nodeType.prototype.onSerialize=function(data) {
            serialized?.apply(this,arguments);data.properties ||= {};
            const prior=this.properties?.greymonkey_state;
            data.properties.greymonkey_state={version:1,values:{...(prior?.values || {}),...savedWidgets(this)},per_type:clonePersistedData(prior?.per_type || {})};
        };
        nodeType.prototype.onConfigure=function(data) {
            this.greymonkeyRestoring=true;
            try {
                configured?.apply(this,arguments);
                const values=legacyValues(this,data);
                if(values){
                    restore(this,values);this.properties ||= {};
                    this.properties.greymonkey_state={version:1,values:{...values},per_type:clonePersistedData(data.properties?.greymonkey_state?.per_type || data.properties?.greymonkey_subject_type_values || {})};
                } else if(Object.hasOwn(V2,nodeData.name)) {
                    this.greymonkeyMigrationAmbiguous=true;
                    toast(`Node ${this.id}: legacy layout could not be mapped safely. Review selections before upgrading.`);
                }
                this.greymonkeySetActiveType?.();this.greymonkeyFilter?.();
            } finally {this.greymonkeyRestoring=false;}
        };
        nodeType.prototype.onExecuted=function(message) {
            executed?.apply(this,arguments);
            if(Array.isArray(message.greymonkey_text))for(const [index,label] of ["Positive prompt","Negative prompt"].entries())textPreview(this,label,message.greymonkey_text[index]);
            if(Array.isArray(message.greymonkey_warnings))textPreview(this,"Warnings",message.greymonkey_warnings.length?message.greymonkey_warnings.join("\n"):"No warnings",60);
            app.graph?.setDirtyCanvas(true,true);
        };
    },
});
