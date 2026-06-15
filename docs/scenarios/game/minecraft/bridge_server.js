/**
 * mineflayer bridge — HTTP API + 3D viewer for Minecraft bot.
 *
 * Usage:
 *   node bridge_server.js
 *
 * Env vars: MC_HOST, MC_PORT, BOT_NAME, MC_VERSION, API_PORT, VIEWER_PORT
 *
 * Endpoints:
 *   GET  /health           → bot status
 *   GET  /state            → bot position, nearby blocks, entities, chat, inventory_items
 *   POST /action           → execute one action
 *   GET  /phase            → benchmark phase + counters
 *   POST /phase            → set benchmark phase (optionally reset counters)
 *   POST /benchmark/reset  → run a full tech-tree benchmark world setup
 * 
 * 3D viewer on port 3007 (prismarine-viewer).
 *
 * Usage:
 *   $env:MC_HOST="localhost"; $env:MC_PORT="25565"; node bridge_server.js
 */

const express = require('express');
const mineflayer = require('mineflayer');
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder');
const collectBlock = require('mineflayer-collectblock');
const Vec3 = require('vec3'); // bot.blockAt() needs a Vec3; plain {x,y,z} throws "pos.floored is not a function"
const app = express();
app.use(express.json());

const HOST = process.env.MC_HOST || 'localhost';
const PORT = parseInt(process.env.MC_PORT || '25565', 10);
const BOT_NAME = process.env.BOT_NAME || 'paos';
const API_PORT = parseInt(process.env.BRIDGE_PORT || '3001', 10);
const VIEWER_PORT = parseInt(process.env.VIEWER_PORT || '3007', 10);
const STATE_RADIUS = parseInt(process.env.STATE_RADIUS || '5', 10);

let bot = null, botSpawned = false, spawnTime = 0;
let viewerStarted = false; // prismarine-viewer binds a port once; spawn fires again on respawn
let recentChats = []; // recent chat messages from other players, exposed via /state last_chats

// ── Benchmark phase tracking ────────────────────────────────────
// Mirror of PhyAgentOS/benchmarks/minecraft/techtree phase semantics.
// The Python adapter posts /phase before/after a benchmark reset so the
// bridge knows the bot is in a benchmark-driven episode.
let currentPhase = 'idle';
let phaseCounters = { resets: 0, steps: 0 };

// ── Bot ─────────────────────────────────────────────────────────
const MC_VERSION = process.env.MC_VERSION || '1.20.4';

function createBot() {
    bot = mineflayer.createBot({ host: HOST, port: PORT, username: BOT_NAME, version: MC_VERSION });
    bot.loadPlugin(pathfinder);
    bot.loadPlugin(collectBlock.plugin);

    bot.on('spawn', () => {
        botSpawned = true; spawnTime = Date.now();
        console.log(`[bridge] Bot spawned: ${BOT_NAME} (MC ${MC_VERSION})`);

        // mineflayer-collectblock init
        if (bot.collectBlock) {
            if (!bot.collectBlock.chestLocations) bot.collectBlock.chestLocations = new Map();
            if (!bot.collectBlock.chestsToOpen) bot.collectBlock.chestsToOpen = [];
            if (!bot.collectBlock.tempChests) bot.collectBlock.tempChests = new Map();
        }

        if (!viewerStarted) {
            try {
                const { mineflayer: mineflayerViewer } = require('prismarine-viewer');
                mineflayerViewer(bot, { port: VIEWER_PORT, firstPerson: true });
                viewerStarted = true;
                console.log(`[bridge] 3D viewer (first-person) on http://localhost:${VIEWER_PORT}`);
            } catch (e) { console.log(`[bridge] 3D viewer unavailable: ${e.message}`); }
        }
    });

    bot.on('death', () => { botSpawned = false; setTimeout(() => { if (bot) bot.respawn(); }, 3000); });
    bot.on('kicked', (r) => { console.log(`[bridge] Kicked: ${r}`); botSpawned = false; });
    bot.on('error', (e) => console.error(`[bridge] Error: ${e.message}`));
    bot.on('end', (r) => { console.log(`[bridge] Disconnected: ${r}`); botSpawned = false; });

    bot.on('chat', (username, message) => {
        if (username === BOT_NAME) return;
        recentChats.push({ username, message, time: Date.now() });
    });
}

// ── State ───────────────────────────────────────────────────────
function getState() {
    if (!bot || !bot.entity) return { bot: null, error: 'not spawned' };

    const pos = bot.entity.position;
    const nearbyBlocks = [];
    const nearbyEntities = [];

    // nearby blocks (radius = STATE_RADIUS)
    const r = STATE_RADIUS;
    for (let dx = -r; dx <= r; dx++) {
        for (let dy = -r; dy <= r; dy++) {
            for (let dz = -r; dz <= r; dz++) {
                const b = bot.blockAt(pos.offset(dx, dy, dz));
                if (b && b.name !== 'air') {
                    nearbyBlocks.push({
                        name: b.name,
                        position: { x: pos.x + dx, y: pos.y + dy, z: pos.z + dz }
                    });
                }
            }
        }
    }

    // nearby entities
    for (const id in bot.entities) {
        const e = bot.entities[id];
        if (e === bot.entity) continue;
        const dist = e.position.distanceTo(pos);
        if (dist <= STATE_RADIUS * 2) {
            nearbyEntities.push({
                type: e.name || e.type || 'unknown',
                position: { x: e.position.x, y: e.position.y, z: e.position.z },
                health: e.health,
            });
        }
    }

    // players
    const players = Object.values(bot.players).map(p => ({
        username: p.username,
        position: {
            x: Math.round(p.entity.position.x * 10) / 10,
            y: Math.round(p.entity.position.y * 10) / 10,
            z: Math.round(p.entity.position.z * 10) / 10,
        },
    }));

    // inventory hotbar
    const hotbarSlots = bot.inventory.slots.slice(36, 45);
    const hotbar = hotbarSlots.map((item, i) => item ? {
        slot: i,
        name: item.name,
        count: item.count,
    } : null).filter(Boolean);

    // full inventory flattened into the evaluator-friendly shape:
    //   [{ name: "minecraft:oak_log", count: 1 }, ...]
    // so PhyAgentOS.benchmarks.minecraft.techtree.evaluator.inventory_counts
    // can score the bridge state directly without a second adapter layer.
    const inventory_items = bot.inventory.items().map((item) => ({
        name: mcName(item.name),
        count: item.count,
    }));

    return {
        bot: {
            position: { x: pos.x, y: pos.y, z: pos.z },
            rotation: { yaw: bot.entity.yaw, pitch: bot.entity.pitch },
            on_ground: bot.entity.onGround,
            health: bot.health,
        },
        health: bot.health,
        hunger: bot.food,
        dimension: bot.game.dimension,
        world: { time: bot.time.timeOfDay, raining: bot.isRaining },
        player_list: Object.keys(bot.players),
        nearby_blocks: nearbyBlocks,
        nearby_entities: nearbyEntities,
        players: players,
        inventory: { hotbar },
        inventory_items,
        last_chats: recentChats,
    };
}

// ── Actions ─────────────────────────────────────────────────────
function executeAction(action) {
    return new Promise((resolve) => {
        if (!bot || !bot.entity) return resolve({ ok: false, result: 'bot not spawned' });
        const t = action.type, p = action.params || {};
        try {
            switch (t) {
                case 'move': {
                    const pos = bot.entity.position;
                    let gx, gy, gz;
                    if (p.forward != null) {
                        const dist = parseFloat(p.forward);
                        gx = pos.x - Math.sin(bot.entity.yaw) * dist;
                        gy = pos.y;
                        gz = pos.z + Math.cos(bot.entity.yaw) * dist;
                    } else {
                        gx = p.absolute ? parseFloat(p.dx) : pos.x + parseFloat(p.dx || 0);
                        gy = p.absolute ? parseFloat(p.dy) : pos.y + parseFloat(p.dy || 0);
                        gz = p.absolute ? parseFloat(p.dz) : pos.z + parseFloat(p.dz || 0);
                    }
                    bot.pathfinder.setMovements(new Movements(bot));
                    bot.pathfinder.setGoal(new goals.GoalBlock(Math.floor(gx), Math.floor(gy), Math.floor(gz)));
                    resolve({ ok: true, result: `moving to (${gx.toFixed(1)}, ${gy.toFixed(1)}, ${gz.toFixed(1)})` }); break;
                }
                case 'look': {
                    const yaw = p.yaw != null ? parseFloat(p.yaw) * Math.PI / 180 : bot.entity.yaw;
                    const pitch = p.pitch != null ? parseFloat(p.pitch) * Math.PI / 180 : bot.entity.pitch;
                    bot.look(yaw, pitch, true);
                    resolve({ ok: true, result: 'ok' });
                    break;
                }
                case 'jump': bot.setControlState('jump', true); setTimeout(() => bot.setControlState('jump', false), parseInt(p.duration_ms || 500)); resolve({ ok: true, result: 'ok' }); break;
                case 'sneak': bot.setControlState('sneak', p.start !== false); resolve({ ok: true, result: 'ok' }); break;
                case 'sprint': bot.setControlState('sprint', p.start !== false); resolve({ ok: true, result: 'ok' }); break;
                case 'dig': {
                    const Vec3 = bot.entity.position.constructor;
                    const b = bot.blockAt(new Vec3(Math.floor(p.x), Math.floor(p.y), Math.floor(p.z)));
                    if (!b || b.name === 'air') return resolve({ ok: false, result: 'no block' });
                    bot.dig(b, (e) => resolve(e ? { ok: false, result: e.message } : { ok: true, result: `dug ${b.name}` })); break;
                }
                case 'place': {
                    const Vec3 = bot.entity.position.constructor;
                    const rb = bot.blockAt(new Vec3(Math.floor(p.x), Math.floor(p.y), Math.floor(p.z)));
                    if (!rb) return resolve({ ok: false, result: 'no reference block' });
                    const fv = [{ x: 0, y: -1, z: 0 }, { x: 0, y: 1, z: 0 }, { x: 0, y: 0, z: -1 }, { x: 0, y: 0, z: 1 }, { x: -1, y: 0, z: 0 }, { x: 1, y: 0, z: 0 }];
                    bot.placeBlock(rb, fv[parseInt(p.face) || 1], (e) => resolve(e ? { ok: false, result: e.message } : { ok: true, result: 'placed' })); break;
                }
                case 'attack': {
                    let target = p.entity_id ? bot.entities[p.entity_id] : null;
                    if (!target && p.target_type) for (const id in bot.entities) if (bot.entities[id] !== bot.entity && bot.entities[id].name === p.target_type) { target = bot.entities[id]; break; }
                    if (!target) return resolve({ ok: false, result: 'no target' });
                    bot.attack(target); resolve({ ok: true, result: 'attacked' }); break;
                }
                case 'interact': { const e = bot.entities[p.entity_id]; if (!e) return resolve({ ok: false, result: 'entity not found' }); bot.activateEntity(e); resolve({ ok: true, result: 'ok' }); break; }
                case 'use': bot.activateItem(); resolve({ ok: true, result: 'ok' }); break;
                case 'select_slot': { const s = Math.max(0, Math.min(8, parseInt(p.slot || 0))); bot.setQuickBarSlot(s); resolve({ ok: true, result: `slot ${s}` }); break; }
                case 'drop': { const it = p.slot != null ? bot.inventory.slots[parseInt(p.slot)] : bot.inventory.slots[bot.quickBarSlot]; if (!it) return resolve({ ok: false, result: 'nothing to drop' }); bot.tossStack(it); resolve({ ok: true, result: `dropped ${it.name}` }); break; }
                case 'chat': { const m = String(p.message || ''); if (!m) return resolve({ ok: false, result: 'empty' }); bot.chat(m); resolve({ ok: true, result: `sent: ${m}` }); break; }
                case 'collect': {
                    const mcData = require('minecraft-data')(bot.version);
                    const it = mcData.itemsByName[p.block_type] || mcData.blocksByName[p.block_type];
                    if (!it) return resolve({ ok: false, result: `unknown: ${p.block_type}` });
                    console.log(`[bridge] collect: ${p.block_type} x${p.count} (id=${it.id})`);
                    try {
                        bot.collectBlock.collect(it, { count: parseInt(p.count || 1) }, (e) => {
                            if (e) console.log(`[bridge] collect failed: ${e.message}`);
                            else console.log(`[bridge] collect done: ${p.count}x ${p.block_type}`);
                            resolve(e ? { ok: false, result: e.message } : { ok: true, result: `collected ${p.count}x ${p.block_type}` });
                        });
                    } catch (e2) {
                        console.log(`[bridge] collectBlock threw: ${e2.message}`);
                        resolve({ ok: false, result: `collectBlock error: ${e2.message}` });
                    }
                    break;
                }
                case 'equip': { const item = bot.inventory.items().find(i => i.name === p.item); if (!item) return resolve({ ok: false, result: `no ${p.item}` }); bot.equip(item, p.destination || 'hand', (e) => resolve(e ? { ok: false, result: e.message } : { ok: true, result: 'ok' })); break; }
                case 'craft': {
                    const mcData = require('minecraft-data')(bot.version);
                    const id = mcData.itemsByName[p.recipe_id]; if (!id) return resolve({ ok: false, result: `unknown: ${p.recipe_id}` });
                    const recipes = bot.recipesFor(id.id, null, 1, null); if (!recipes.length) return resolve({ ok: false, result: 'no recipe' });
                    bot.craft(recipes[0], parseInt(p.count || 1), null, (e) => resolve(e ? { ok: false, result: e.message } : { ok: true, result: `crafted ${p.count}x ${p.recipe_id}` })); break;
                }
                default: resolve({ ok: false, result: `unknown type: ${t}` });
            }
        } catch (e) { resolve({ ok: false, result: e.message }); }
    });
}

// ── Benchmark setup ─────────────────────────────────────────────
// Worlds an executor-independent Minecraft tech-tree benchmark task:
// arena isolation, inventory reset, item grants (with enchantment NBT),
// and relative block placement. Mirrors the semantics of
// PhyAgentOS/benchmarks/minecraft/techtree WorldSetup so the Python
// adapter can delegate the whole reset to one POST /benchmark/reset.

const DEFAULT_ARENA = {
    enabled: true,
    origin: [-2000, 80, -2000],
    clear_radius: 8,
    clear_height: 6,
    floor_block: 'smooth_stone',
    boundary_block: 'stone_bricks',
};

function mcName(n) {
    return String(n).startsWith('minecraft:') ? String(n) : `minecraft:${n}`;
}

// Build a /give command, including enchantment NBT when requested.
//   item = { item, count, enchantments: [{ id, level }] }
function giveCmd(item) {
    let suffix = '';
    const enchs = Array.isArray(item.enchantments) ? item.enchantments : [];
    if (enchs.length) {
        const entries = enchs.map((en) => {
            const id = String(en.id || '').replace('minecraft:', '');
            const lvl = parseInt(en.level || 1, 10);
            return `{id:"minecraft:${id}",lvl:${lvl}}`;
        }).join(',');
        suffix = `{Enchantments:[${entries}]}`;
    }
    const count = Math.max(1, parseInt(item.count || 1, 10));
    return `/give @s ${mcName(item.item)}${suffix} ${count}`;
}

// Send a Minecraft server command via the bot's chat channel and wait
// briefly for the server to apply it. Server commands (/tp /fill /give
// /setblock /clear) are asynchronous, so a short delay between steps
// keeps multi-step resets from racing (e.g. /tp before /fill).
const COMMAND_SETTLE_MS = 150;
function cmd(c) {
    return new Promise((resolve) => {
        bot.chat(c);
        setTimeout(() => resolve({ ok: true, cmd: c }), COMMAND_SETTLE_MS);
    });
}

async function benchmarkReset(setup) {
    if (!bot || !bot.entity) throw new Error('bot not spawned');
    const arena = { ...DEFAULT_ARENA, ...(setup.arena || {}) };
    const origin = arena.enabled
        ? arena.origin.map((v) => parseInt(v, 10))
        : [
            Math.floor(bot.entity.position.x),
            Math.floor(bot.entity.position.y),
            Math.floor(bot.entity.position.z),
        ];
    const [x, y, z] = origin;
    const seq = [];

    if (arena.enabled === true || arena.enabled === undefined) {
        const R = Math.max(1, parseInt(arena.clear_radius, 10));
        const H = Math.max(1, parseInt(arena.clear_height, 10));
        const fy = y - 1;
        seq.push(`/tp @s ${x} ${y} ${z} 0 0`);
        seq.push(`/fill ${x - R} ${y} ${z - R} ${x + R} ${y + H} ${z + R} air`);
        seq.push(`/fill ${x - R} ${fy} ${z - R} ${x + R} ${fy} ${z + R} ${mcName(arena.floor_block)}`);
        const b = mcName(arena.boundary_block);
        seq.push(`/fill ${x - R} ${fy} ${z - R} ${x + R} ${fy} ${z - R} ${b}`);
        seq.push(`/fill ${x - R} ${fy} ${z + R} ${x + R} ${fy} ${z + R} ${b}`);
        seq.push(`/fill ${x - R} ${fy} ${z - R} ${x - R} ${fy} ${z + R} ${b}`);
        seq.push(`/fill ${x + R} ${fy} ${z - R} ${x + R} ${fy} ${z + R} ${b}`);
    }
    if (setup.clear_inventory !== false) seq.push('/clear @s');
    for (const it of (setup.inventory || [])) seq.push(giveCmd(it));
    for (const blk of (setup.blocks || [])) {
        const rel = blk.relative || [0, 0, 0];
        seq.push(`/setblock ${x + parseInt(rel[0], 10)} ${y + parseInt(rel[1], 10)} ${z + parseInt(rel[2], 10)} ${mcName(blk.block)}`);
    }

    currentPhase = 'reset';
    phaseCounters = { resets: phaseCounters.resets + 1, steps: 0 };
    for (const c of seq) await cmd(c);
    currentPhase = 'idle';
    return { ok: true, commands: seq.length, phase: currentPhase, counters: phaseCounters };
}

// ── HTTP ────────────────────────────────────────────────────────
app.get('/health', (_req, res) => res.json({ ok: true, bot_spawned: botSpawned, uptime_seconds: botSpawned ? Math.floor((Date.now() - spawnTime) / 1000) : 0 }));
app.get('/state', (_req, res) => res.json(getState()));
app.post('/action', async (req, res) => {
    if (!req.body?.type) return res.status(400).json({ ok: false, error: 'missing type' });
    res.json(await executeAction(req.body));
});

// Benchmark phase marker: lets an external benchmark announce that the
// bot is entering/leaving a benchmark-driven episode, optionally
// resetting the step counter. Idempotent and safe to call anytime.
app.post('/phase', (req, res) => {
    const { phase, reset_counters, source } = req.body || {};
    currentPhase = phase || 'idle';
    if (reset_counters) phaseCounters = { resets: phaseCounters.resets + 1, steps: 0 };
    console.log(`[bridge] phase=${currentPhase} source=${source || '-'}`);
    res.json({ ok: true, phase: currentPhase, counters: phaseCounters });
});

// Execute a full tech-tree benchmark reset in one call. The body is a
// WorldSetup dict (arena, clear_inventory, inventory, blocks). Returns
// the number of server commands issued and the final phase.
app.post('/benchmark/reset', async (req, res) => {
    try {
        res.json(await benchmarkReset(req.body || {}));
    } catch (e) {
        console.log(`[bridge] benchmark/reset failed: ${e.message}`);
        res.status(500).json({ ok: false, error: e.message });
    }
});

// Expose benchmark phase so a benchmark client can confirm the bridge
// has settled into idle after a reset.
app.get('/phase', (_req, res) => res.json({ ok: true, phase: currentPhase, counters: phaseCounters }));

// ── Start ───────────────────────────────────────────────────────
console.log(`[bridge] Starting for Minecraft ${MC_VERSION}`);
createBot();
app.listen(API_PORT, '0.0.0.0', () => console.log(`[bridge] HTTP API listening on port ${API_PORT}`));
