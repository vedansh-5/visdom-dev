/* Copyright 2017-present, The Visdom Authors */

import http from 'k6/http';
import ws from 'k6/ws';
import exec from 'k6/execution';
import { check, sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';

const BASE = (__ENV.BASE || 'https://visdom.dev').replace(/\/$/, '');
const API = `${BASE}/api/v1`;
const SOCKET_BASE = BASE.replace(/^http/, 'ws');
const RUN = __ENV.RUN || 'r1';

const USERS = Number(__ENV.USERS || 1);
const WORKSPACES = Number(__ENV.WORKSPACES || 1);
const RAMP = __ENV.RAMP || `${Math.ceil(USERS * 2.5)}s`;
const HOLD = __ENV.HOLD || '2m';
const WATCH_SECONDS = Number(__ENV.WATCH_SECONDS || 60);
const STEP_MS = Number(__ENV.STEP_MS || 1000);
const SIGN_IN_AGAIN_AFTER_MS = 12 * 60 * 1000;

const PLOTS = ['loss', 'accuracy'];
const JSON_HEADERS = { 'Content-Type': 'application/json' };

if (!/^[a-z0-9]{1,12}$/.test(RUN)) {
    throw new Error('RUN must be 1 to 12 lowercase letters or digits, for example RUN=t1');
}
if (WATCH_SECONDS > 120) {
    throw new Error('WATCH_SECONDS must be 120 or less, or the sign-in runs out mid-watch');
}
if (!Number.isInteger(WORKSPACES) || WORKSPACES < 1 || WORKSPACES > 10) {
    throw new Error('WORKSPACES must be a whole number from 1 to 10');
}

export const options = {
    userAgent: 'visdom-loadtest/k6',
    noCookiesReset: true,
    summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max'],
    scenarios: {
        users: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: RAMP, target: USERS },
                { duration: HOLD, target: USERS },
                { duration: '10s', target: 0 },
            ],
            gracefulRampDown: `${WATCH_SECONDS + 20}s`,
            gracefulStop: `${WATCH_SECONDS + 20}s`,
        },
    },
    thresholds: {
        checks: ['rate>0.99'],
        http_req_failed: ['rate<0.01'],
        'http_req_duration{kind:plot}': ['p(95)<500'],
        'http_req_duration{kind:console}': ['p(95)<800'],
        plot_delivery_ms: ['p(95)<1000'],
        plots_refused: ['count==0'],
    },
};

const signups = new Counter('signups');
const rateLimited = new Counter('rate_limited');
const plotsSent = new Counter('plots_sent');
const plotsRefused = new Counter('plots_refused');
const updatesSeen = new Counter('updates_seen');
const plotDelivery = new Trend('plot_delivery_ms', true);

const TRACE = {
    name: '1',
    type: 'scatter',
    mode: 'lines',
    textposition: 'right',
    line: {},
    marker: { size: 10, symbol: 'dot', line: { color: '#000000', width: 0.5 } },
};

function plotOptions(title) {
    return {
        title,
        markers: false,
        fillarea: false,
        mode: 'lines',
        markersymbol: 'dot',
        markersize: 10,
        markerborderwidth: 0.5,
    };
}

let me = null;

function patiently(send) {
    let res = send();
    for (let attempt = 1; res.status === 429 && attempt <= 10; attempt += 1) {
        rateLimited.add(1);
        sleep(attempt);
        res = send();
    }
    return res;
}

function signIn(user) {
    const loginRes = patiently(() =>
        http.post(
            `${API}/auth/login`,
            { username: user.email, password: user.password },
            {
                tags: { kind: 'auth', name: 'sign in' },
                responseCallback: http.expectedStatuses(200, 429),
            }
        )
    );

    if (!check(loginRes, { 'signed in': (r) => r.status === 200 })) {
        return false;
    }
    user.token = loginRes.json('access_token');
    user.console = {
        headers: {
            Authorization: `Bearer ${user.token}`,
            'Content-Type': 'application/json',
        },
        tags: { kind: 'console' },
    };

    user.signedInAt = Date.now();
    return true;
}

function stopIfThePlanRefused(res, what) {
    if (res.status === 402) {
        exec.test.abort(
            `The plan refused ${what}. WORKSPACES=${WORKSPACES} needs the limit bypass ` +
                'switched on in the admin console (or Pro accounts). WORKSPACES=1 fits the Free plan.'
        );
    }
}

function ownWorkspaces(user, n) {
    const mine = http.get(`${API}/workspaces`, user.console);
    const have = (mine.status === 200 ? mine.json() : []).map((workspace) => workspace.slug);
    const slugs = [];
    for (let k = 1; k <= WORKSPACES; k += 1) {
        const slug = k === 1 ? user.slug : `${user.slug}-${k}`;
        if (!have.includes(slug)) {
            const created = http.post(
                `${API}/workspaces`,
                JSON.stringify({ name: `Load ${RUN} ${n} ${k}`, slug }),
                Object.assign({}, user.console, {
                    responseCallback: http.expectedStatuses(201, 402),
                })
            );
            stopIfThePlanRefused(created, 'a workspace');
            if (!check(created, { 'workspace created': (r) => r.status === 201 })) {
                return null;
            }
        }
        slugs.push(slug);
    }
    return slugs;
}

function freshKeys(user, slugs) {
    const keys = http.get(`${API}/keys`, user.console);
    for (const key of keys.status === 200 ? keys.json() : []) {
        http.del(`${API}/keys/${key.id}`, null, {
            headers: user.console.headers,
            tags: { kind: 'console', name: 'remove key' },
        });
    }
    const places = [];
    for (const slug of slugs) {
        const made = http.post(
            `${API}/keys`,
            JSON.stringify({ name: `training ${slug}`, scope: 'org' }),
            Object.assign({}, user.console, {
                responseCallback: http.expectedStatuses(201, 402),
            })
        );
        stopIfThePlanRefused(made, 'an API key');
        if (!check(made, { 'key created': (r) => r.status === 201 })) {
            return null;
        }
        places.push({
            slug,
            plot: {
                'X-API-KEY': made.json('raw_key'),
                'X-Visdom-Workspace': slug,
                'Content-Type': 'application/json',
            },
        });
    }
    return places;
}

function newUser() {
    const n = exec.vu.idInTest;
    const user = {
        email: `load.${RUN}.${n}@example.com`,
        password: `Load-${RUN}-${n}-pass`,
        slug: `load-${RUN}-${n}`,
    };

    // sign up (201 = created, 400 = already exists from previous run)
    const signupRes = patiently(() =>
        http.post(
            `${API}/auth/register`,
            JSON.stringify({ email: user.email, password: user.password }),
            {
                headers: JSON_HEADERS,
                tags: { kind: 'auth', name: 'sign up' },
                responseCallback: http.expectedStatuses(201, 400, 429),
            }
        )
    );
    if (signupRes.status === 201) signups.add(1);

    // sign in
    if (!signIn(user)) {
        return null;
    }

    // Who am I check
    http.get(`${API}/auth/me`, user.console);
    http.get(`${API}/workspaces/invites/pending`, user.console);

    const slugs = ownWorkspaces(user, n);
    if (slugs === null) {
        return null;
    }
    user.places = freshKeys(user, slugs);
    if (user.places === null) {
        return null;
    }
    return user;
}

function sendPoint(place, env, win, step, value) {
    const exists = http.post(`${BASE}/vis/win_exists`, JSON.stringify({ win, eid: env }), {
        headers: place.plot,
        tags: { kind: 'plot', name: 'win_exists' },
    });
    const point = {
        data: [Object.assign({ x: [step], y: [value] }, TRACE)],
        win,
        eid: env,
        opts: plotOptions(win),
    };

    let endpoint;
    let name;
    if (exists.body === 'true') {
        Object.assign(point, { layout: {}, name: null, append: true });
        endpoint = 'update';
        name = 'append point';
    } else {
        point.layout = {
            showlegend: false,
            title: { text: win },
            margin: { l: 60, r: 60, t: 60, b: 60 },
        };
        endpoint = 'events';
        name = 'create plot';
    }
    const body = JSON.stringify(point);

    const sentAt = Date.now();
    const res = http.post(`${BASE}/vis/${endpoint}`, body, {
        headers: place.plot,
        tags: { kind: 'plot', name },
    });
    if (res.status !== 200) {
        plotsRefused.add(1);
        return null;
    }
    plotsSent.add(1);
    return sentAt;
}

function trainAndWatch(place, env) {
    const waiting = {};
    let tick = 0;
    let arrived = 0;

    const logNextPoint = () => {
        const win = PLOTS[tick % PLOTS.length];
        const step = Math.floor(tick / PLOTS.length);
        tick += 1;
        const loss = 1 / (1 + step * 0.1);
        const sentAt = sendPoint(place, env, win, step, win === 'loss' ? loss : 1 - loss);
        if (sentAt !== null && waiting[win]) {
            waiting[win].push(sentAt);
        }
    };

    PLOTS.forEach(logNextPoint);

    const page = http.get(`${BASE}/vis/w/${place.slug}/`, {
        tags: { kind: 'page', name: 'plots page' },
    });
    check(page, {
        'plots page loaded': (r) => r.status === 200 && r.url.indexOf('/login') === -1,
    });

    const opened = ws.connect(
        `${SOCKET_BASE}/vis/w/${place.slug}/socket`,
        { tags: { kind: 'socket' } },
        (socket) => {
            socket.on('message', (raw) => {
                let message;
                try {
                    message = JSON.parse(raw);
                } catch (e) {
                    return;
                }
                if (message.command === 'register') {
                    http.post(
                        `${BASE}/vis/w/${place.slug}/env/${env}`,
                        JSON.stringify({ sid: message.data }),
                        { headers: JSON_HEADERS, tags: { kind: 'page', name: 'select run' } }
                    );
                    PLOTS.forEach((win) => {
                        waiting[win] = [];
                    });
                    socket.setInterval(logNextPoint, STEP_MS / PLOTS.length);
                    return;
                }
                if (message.command === 'window_update') {
                    updatesSeen.add(1);
                    arrived += 1;
                    const sentAt = (waiting[message.win] || []).shift();
                    if (sentAt) {
                        plotDelivery.add(Date.now() - sentAt);
                    }
                }
            });
            socket.setTimeout(() => socket.close(), WATCH_SECONDS * 1000);
        }
    );
    check(opened, { 'plots page connected': (r) => r && r.status === 101 });
    check(arrived, { 'new points reached the page': (count) => count > 0 });
}

function lookAround(user) {
    http.get(`${API}/usage`, user.console);
    http.get(`${API}/billing/subscription`, user.console);
    http.get(`${API}/keys`, user.console);
    http.get(`${API}/workspaces`, user.console);
}

export default function () {
    if (me === null) {
        me = newUser();
        if (me === null) {
            sleep(5);
            return;
        }
    }
    if (Date.now() - me.signedInAt > SIGN_IN_AGAIN_AFTER_MS && !signIn(me)) {
        sleep(5);
        return;
    }

    const loop = exec.vu.iterationInScenario;
    trainAndWatch(me.places[loop % me.places.length], `run-${loop}`);
    lookAround(me);
    sleep(2 + Math.random() * 3);
}
