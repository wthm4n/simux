require('dotenv').config();

const cors = require('cors');
const express = require('express');
const rateLimit = require('express-rate-limit');
const amqplib = require('amqplib');
const { v4: uuidv4 } = require('uuid');
const { Pool } = require('pg');
const bcrypt = require('bcrypt');
const jwt = require('jsonwebtoken');
const os = require('os');

const app = express();
app.use(express.json());
app.use(cors());

const JWT_SECRET = process.env.JWT_SECRET;
const PORT       = parseInt(process.env.PORT || '3000', 10);
const JUDGE_API  = process.env.JUDGE_API_URL || 'http://localhost:5050';

if (!JWT_SECRET) {
    console.error('FATAL: JWT_SECRET is not set in .env');
    process.exit(1);
}

// ─────────────────────────────────────────────────────────────
// Terminal UI Helpers (unchanged)
// ─────────────────────────────────────────────────────────────

const C = {
    reset: "\x1b[0m",
    bold: "\x1b[1m",
    dim: "\x1b[2m",
    red: "\x1b[31m",
    green: "\x1b[32m",
    yellow: "\x1b[33m",
    cyan: "\x1b[36m",
    brightRed: "\x1b[91m",
    brightGreen: "\x1b[92m",
    brightYellow: "\x1b[93m",
    brightBlue: "\x1b[94m",
    brightMagenta: "\x1b[95m",
    brightCyan: "\x1b[96m",
    brightWhite: "\x1b[97m",
};

function color(text, ...codes) { return codes.join('') + text + C.reset; }
function timestamp() { return color(`[${new Date().toLocaleTimeString()}]`, C.dim); }
function divider(char = '━', width = 72) { console.log(color(char.repeat(width), C.dim)); }

function header(title) {
    divider();
    console.log(color(' SIMUX API ', C.bold, C.brightMagenta) + color(` ${title}`, C.brightCyan));
    divider();
}

function log(type, msg) {
    const styles = {
        info:  ['●', C.brightBlue],
        ok:    ['✔', C.brightGreen],
        warn:  ['⚠', C.brightYellow],
        error: ['✖', C.brightRed],
        dim:   ['·', C.dim],
    };
    const [icon, clr] = styles[type] || ['•', C.reset];
    console.log(` ${timestamp()} ${color(icon, clr)} ${msg}`);
}

class Spinner {
    constructor(label) {
        this.label = label;
        this.frames = ['⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏'];
        this.current = 0;
        this.interval = null;
    }
    start() {
        this.interval = setInterval(() => {
            process.stdout.write(`\r ${color(this.frames[this.current], C.brightCyan)} ${color(this.label, C.dim)}`);
            this.current = (this.current + 1) % this.frames.length;
        }, 80);
        return this;
    }
    stop(ok = true, finalMsg = null) {
        clearInterval(this.interval);
        process.stdout.write('\r\x1b[K');
        const icon = ok ? color('✔', C.brightGreen) : color('✖', C.brightRed);
        console.log(` ${icon} ${finalMsg || this.label}`);
    }
}

// ─────────────────────────────────────────────────────────────
// Request Logger
// ─────────────────────────────────────────────────────────────

app.use((req, res, next) => {
    const start = Date.now();
    res.on('finish', () => {
        const ms = Date.now() - start;
        let statusColor = C.brightGreen;
        if (res.statusCode >= 500) statusColor = C.brightRed;
        else if (res.statusCode >= 400) statusColor = C.brightYellow;
        log('info',
            `${color(req.method.padEnd(6), C.brightCyan)} ` +
            `${req.originalUrl} ` +
            `${color(res.statusCode, statusColor)} ` +
            `${color(`${ms}ms`, C.dim)}`
        );
    });
    next();
});

// ─────────────────────────────────────────────────────────────
// Rate Limiters
// ─────────────────────────────────────────────────────────────

// /run: max 10 requests per minute per IP
const runLimiter = rateLimit({
    windowMs: 60 * 1000,
    max: 10,
    standardHeaders: true,
    legacyHeaders: false,
    message: { error: 'too many run requests, slow down' },
});

// /submit: max 20 per minute per IP
const submitLimiter = rateLimit({
    windowMs: 60 * 1000,
    max: 20,
    standardHeaders: true,
    legacyHeaders: false,
    message: { error: 'too many submissions, slow down' },
});

// /ai/generate-testcases: max 5 per minute per IP (expensive)
const aiLimiter = rateLimit({
    windowMs: 60 * 1000,
    max: 5,
    standardHeaders: true,
    legacyHeaders: false,
    message: { error: 'too many AI requests, slow down' },
});

// ─── DB pool ─────────────────────────────────────────────────

const pool = new Pool({
    host:     process.env.DB_HOST,
    database: process.env.DB_NAME,
    user:     process.env.DB_USER,
    password: process.env.DB_PASSWORD,
    port:     parseInt(process.env.DB_PORT || '5432', 10),
});

// ─────────────────────────────────────────────────────────────
// RabbitMQ
// ─────────────────────────────────────────────────────────────

let channel = null;

async function getChannel() {
    if (channel) return channel;
    const spinner = new Spinner('Connecting to RabbitMQ...').start();
    try {
        const conn = await amqplib.connect({
            protocol:  'amqp',
            hostname:  process.env.RABBITMQ_HOST,
            username:  process.env.RABBITMQ_USER,
            password:  process.env.RABBITMQ_PASSWORD,
        });
        channel = await conn.createChannel();
        await channel.assertQueue('submissions', { durable: true });
        spinner.stop(true, 'RabbitMQ connected');
        return channel;
    } catch (err) {
        spinner.stop(false, 'RabbitMQ connection failed');
        throw err;
    }
}

// ─────────────────────────────────────────────────────────────
// Auth Middleware
// ─────────────────────────────────────────────────────────────

function requireAuth(req, res, next) {
    const header = req.headers['authorization'];
    if (!header) return res.status(401).json({ error: 'no token' });
    const token = header.split(' ')[1];
    try {
        req.user = jwt.verify(token, JWT_SECRET);
        next();
    } catch {
        res.status(401).json({ error: 'invalid token' });
    }
}

function requireAdmin(req, res, next) {
    requireAuth(req, res, () => {
        if (req.user.role !== 'admin')
            return res.status(403).json({ error: 'admins only' });
        next();
    });
}

// ─────────────────────────────────────────────────────────────
// REGISTER
// ─────────────────────────────────────────────────────────────

app.post('/register', async (req, res) => {
    const { username, email, password } = req.body;
    if (!username || !email || !password)
        return res.status(400).json({ error: 'username, email, password required' });
    try {
        const hash = await bcrypt.hash(password, 10);
        const result = await pool.query(
            `INSERT INTO users (username, email, password) VALUES ($1, $2, $3) RETURNING id, username, role`,
            [username, email, hash]
        );
        log('ok', `New user registered → ${color(username, C.brightCyan)}`);
        res.json(result.rows[0]);
    } catch (err) {
        if (err.code === '23505')
            return res.status(409).json({ error: 'username or email already taken' });
        res.status(500).json({ error: 'db error' });
    }
});

// ─────────────────────────────────────────────────────────────
// LOGIN
// ─────────────────────────────────────────────────────────────

app.post('/login', async (req, res) => {
    const { username, password } = req.body;
    if (!username || !password)
        return res.status(400).json({ error: 'username, password required' });
    try {
        const result = await pool.query(
            `SELECT id, username, password, role FROM users WHERE username = $1`,
            [username]
        );
        if (result.rows.length === 0)
            return res.status(401).json({ error: 'invalid credentials' });
        const user = result.rows[0];
        const match = await bcrypt.compare(password, user.password);
        if (!match)
            return res.status(401).json({ error: 'invalid credentials' });
        const token = jwt.sign(
            { id: user.id, username: user.username, role: user.role },
            JWT_SECRET,
            { expiresIn: '7d' }
        );
        log('ok', `User login → ${color(user.username, C.brightGreen)}`);
        res.json({ token, username: user.username, role: user.role });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'db error' });
    }
});

// ─────────────────────────────────────────────────────────────
// GET PROBLEMS
// ─────────────────────────────────────────────────────────────

app.get('/problems', async (req, res) => {
    try {
        const result = await pool.query(`
            SELECT id, slug, title, difficulty, time_limit, mem_limit, created_at
            FROM problems
            ORDER BY id ASC
        `);
        res.json(result.rows);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'db error' });
    }
});

// ─────────────────────────────────────────────────────────────
// GET SINGLE PROBLEM
// Hidden test cases: send metadata (count, is_sample=false) but
// NOT the input/expected_output — those stay server-side only.
// ─────────────────────────────────────────────────────────────

app.get('/problems/:slug', async (req, res) => {
    try {
        const prob = await pool.query(
            `SELECT id, slug, title, description, difficulty, time_limit, mem_limit
             FROM problems WHERE slug = $1`,
            [req.params.slug]
        );
        if (prob.rows.length === 0)
            return res.status(404).json({ error: 'problem not found' });

        const cases = await pool.query(
            `SELECT input, expected_output, is_sample
             FROM test_cases
             WHERE problem_id = $1
             ORDER BY id ASC`,
            [prob.rows[0].id]
        );

        const sample_cases = cases.rows.filter(tc => tc.is_sample);

        // Hidden cases: send a placeholder object so the frontend can render
        // the tile count and "hidden" badge, but without actual I/O data.
        const hidden_count = cases.rows.filter(tc => !tc.is_sample).length;
        const hidden_placeholders = Array.from({ length: hidden_count }, (_, i) => ({
            is_sample: false,
            input: null,
            expected_output: null,
        }));

        res.json({
            ...prob.rows[0],
            sample_cases,
            // test_cases used by Problem.jsx for tile rendering: samples + hidden placeholders
            test_cases: [...sample_cases, ...hidden_placeholders],
        });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'db error' });
    }
});

// ─────────────────────────────────────────────────────────────
// CREATE PROBLEM
// ─────────────────────────────────────────────────────────────

app.post('/problems', requireAdmin, async (req, res) => {
    const { slug, title, description, difficulty, time_limit, test_cases } = req.body;
    if (!slug || !title || !description || !test_cases?.length)
        return res.status(400).json({ error: 'slug, title, description, test_cases required' });

    const client = await pool.connect();
    try {
        await client.query('BEGIN');
        const prob = await client.query(
            `INSERT INTO problems (slug, title, description, difficulty, time_limit)
             VALUES ($1, $2, $3, $4, $5) RETURNING id`,
            [slug, title, description, difficulty || 'medium', time_limit || 2000]
        );
        const problem_id = prob.rows[0].id;
        for (const tc of test_cases) {
            await client.query(
                `INSERT INTO test_cases (problem_id, input, expected_output, is_sample)
                 VALUES ($1, $2, $3, $4)`,
                [problem_id, tc.input, tc.expected_output, tc.is_sample ?? false]
            );
        }
        await client.query('COMMIT');
        log('ok', `Problem created → ${color(slug, C.brightMagenta)}`);
        res.json({ id: problem_id, slug });
    } catch (err) {
        await client.query('ROLLBACK');
        console.error(err);
        res.status(500).json({ error: err.detail || 'db error' });
    } finally {
        client.release();
    }
});

// ─────────────────────────────────────────────────────────────
// SUBMIT
// ─────────────────────────────────────────────────────────────

app.post('/submit', requireAuth, submitLimiter, async (req, res) => {
    const { problem_slug, language, code } = req.body;
    if (!problem_slug || !language || !code)
        return res.status(400).json({ error: 'problem_slug, language, code required' });

    const SUPPORTED = ['python', 'c', 'cpp', 'java', 'javascript', 'rust'];
    if (!SUPPORTED.includes(language))
        return res.status(400).json({ error: `unsupported language: ${language}` });

    try {
        const prob = await pool.query(
            `SELECT id FROM problems WHERE slug = $1`,
            [problem_slug]
        );
        if (prob.rows.length === 0)
            return res.status(404).json({ error: 'problem not found' });

        const problem_id = prob.rows[0].id;

        // Fetch ALL test cases (including hidden) server-side — never sent to client
        const tcs = await pool.query(
            `SELECT input, expected_output, is_sample FROM test_cases WHERE problem_id = $1 ORDER BY id ASC`,
            [problem_id]
        );
        if (tcs.rows.length === 0)
            return res.status(400).json({ error: 'problem has no test cases' });

        const id = uuidv4();
        await pool.query(
            `INSERT INTO submissions (id, language, code, status, problem_id, user_id)
             VALUES ($1, $2, $3, 'pending', $4, $5)`,
            [id, language, code, problem_id, req.user.id]
        );

        const ch = await getChannel();
        ch.sendToQueue('submissions', Buffer.from(JSON.stringify({
            id, language, code, test_cases: tcs.rows
        })), { persistent: true });

        log('ok', `Submission queued → ${color(id.slice(0, 8), C.brightYellow)}`);
        res.json({ id });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'server error' });
    }
});

// ─────────────────────────────────────────────────────────────
// RUN CODE
// Only runs against sample (public) test cases.
// Response strips expected_output from hidden cases so they
// can never be reconstructed from the browser.
// ─────────────────────────────────────────────────────────────

app.post('/run', requireAuth, runLimiter, async (req, res) => {
    const { problem_slug, language, code } = req.body;
    try {
        const prob = await pool.query(
            `SELECT id FROM problems WHERE slug = $1`,
            [problem_slug]
        );
        if (prob.rows.length === 0)
            return res.status(404).json({ error: 'problem not found' });

        // Only run sample cases on /run — hidden cases stay hidden
        const tcs = await pool.query(
            `SELECT input, expected_output, is_sample
             FROM test_cases
             WHERE problem_id = $1 AND is_sample = true
             ORDER BY id ASC`,
            [prob.rows[0].id]
        );

        const response = await fetch(`${JUDGE_API}/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ language, code, test_cases: tcs.rows }),
        });

        const data = await response.json();
        res.json(data);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'execution failed' });
    }
});

// ─────────────────────────────────────────────────────────────
// MY STATUSES
// ─────────────────────────────────────────────────────────────

app.get('/my-statuses', requireAuth, async (req, res) => {
    try {
        const result = await pool.query(
            `SELECT
                p.slug,
                MAX(CASE
                    WHEN s.verdict = 'AC' THEN 3
                    WHEN s.verdict IS NOT NULL THEN 2
                    ELSE 1
                END) AS score
             FROM submissions s
             JOIN problems p ON p.id = s.problem_id
             WHERE s.user_id = $1
             GROUP BY p.slug`,
            [req.user.id]
        );
        const statuses = {};
        for (const row of result.rows) {
            if (row.score == 3) statuses[row.slug] = 'ac';
            else if (row.score == 2) statuses[row.slug] = 'attempted';
        }
        res.json({ statuses });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'db error' });
    }
});

// ─────────────────────────────────────────────────────────────
// VERDICT
// Auth required — users can only see their own submissions.
// Admins can see all.
// ─────────────────────────────────────────────────────────────

app.get('/verdict/:id', requireAuth, async (req, res) => {
    try {
        const query = req.user.role === 'admin'
            ? `SELECT id, language, status, verdict, time_ms, problem_id, test_results, created_at
               FROM submissions WHERE id = $1`
            : `SELECT id, language, status, verdict, time_ms, problem_id, test_results, created_at
               FROM submissions WHERE id = $1 AND user_id = $2`;

        const params = req.user.role === 'admin'
            ? [req.params.id]
            : [req.params.id, req.user.id];

        const result = await pool.query(query, params);
        if (result.rows.length === 0)
            return res.status(404).json({ error: 'submission not found' });

        const row = result.rows[0];

        // Strip actual_output from hidden test cases before sending to client
        if (row.test_results && Array.isArray(row.test_results)) {
            row.test_results = row.test_results.map(tr => {
                if (!tr.is_sample) {
                    return {
                        n: tr.n,
                        passed: tr.passed,
                        verdict: tr.verdict,
                        time_ms: tr.time_ms,
                        is_sample: false,
                        // No actual_output, no stderr for hidden cases
                    };
                }
                return tr;
            });
        }

        res.json(row);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'db error' });
    }
});

// ─────────────────────────────────────────────────────────────
// MY SUBMISSIONS
// ─────────────────────────────────────────────────────────────

app.get('/my-submissions', requireAuth, async (req, res) => {
    try {
        const result = await pool.query(
            `SELECT
                s.id,
                s.language,
                s.status,
                s.verdict,
                s.time_ms,
                s.created_at,
                p.slug   AS problem_slug,
                p.title  AS problem_title
             FROM submissions s
             JOIN problems p ON p.id = s.problem_id
             WHERE s.user_id = $1
             ORDER BY s.created_at DESC
             LIMIT 100`,
            [req.user.id]
        );
        res.json(result.rows);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'db error' });
    }
});

// ─────────────────────────────────────────────────────────────
// AI TEST CASE GENERATION (backend proxy)
// Keeps the Anthropic API key server-side.
// Admin only.
// ─────────────────────────────────────────────────────────────

app.post('/ai/generate-testcases', requireAdmin, aiLimiter, async (req, res) => {
    const { title, difficulty, time_limit, description, input_format, output_format, constraints, count } = req.body;

    if (!title || !description)
        return res.status(400).json({ error: 'title and description required' });

    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey || apiKey.startsWith('sk-ant-CHANGE')) {
        return res.status(503).json({ error: 'AI generation not configured (ANTHROPIC_API_KEY not set)' });
    }

    const n = Math.min(Math.max(parseInt(count) || 18, 5), 30);

    const prompt = `You are helping build test cases for a competitive programming judge.

Problem: "${title}"
Difficulty: ${difficulty || 'medium'}
Time limit: ${time_limit || 2000}ms

Description:
${description}

${input_format  ? `Input Format:\n${input_format}\n`   : ''}
${output_format ? `Output Format:\n${output_format}\n` : ''}
${constraints   ? `Constraints:\n${constraints}\n`     : ''}

Generate exactly ${n} test cases for this problem. Include:
- 2 basic/trivial cases
- Several small cases
- Edge cases (minimum values, maximum values, zeros, negatives if applicable)
- Corner cases specific to this problem type
- Stress test cases near constraint limits

Respond ONLY with a JSON array. No explanation, no markdown, no backticks. Format:
[{"input": "...", "expected_output": "..."}, ...]

Each input/output should be exactly what would be piped to stdin/stdout.`;

    try {
        const anthropicRes = await fetch('https://api.anthropic.com/v1/messages', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'x-api-key': apiKey,
                'anthropic-version': '2023-06-01',
            },
            body: JSON.stringify({
                model: 'claude-sonnet-4-20250514',
                max_tokens: 4000,
                messages: [{ role: 'user', content: prompt }],
            }),
        });

        const data = await anthropicRes.json();
        if (!anthropicRes.ok) {
            log('error', `Anthropic API error: ${JSON.stringify(data)}`);
            return res.status(502).json({ error: 'AI service error' });
        }

        const text = data.content?.map(b => b.text || '').join('') || '';
        const clean = text.replace(/```json|```/g, '').trim();
        const parsed = JSON.parse(clean);

        if (!Array.isArray(parsed))
            return res.status(502).json({ error: 'AI returned unexpected format' });

        log('ok', `AI generated ${parsed.length} test cases for "${title}"`);
        res.json({ test_cases: parsed });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'AI generation failed' });
    }
});

// ─────────────────────────────────────────────────────────────
// START SERVER
// ─────────────────────────────────────────────────────────────

async function start() {
    header('Backend Server');

    const dbSpin = new Spinner('Connecting to PostgreSQL...').start();
    try {
        await pool.query('SELECT NOW()');
        dbSpin.stop(true, 'PostgreSQL connected');
    } catch (err) {
        dbSpin.stop(false, 'PostgreSQL failed');
        throw err;
    }

    await getChannel();
    divider();

    log('ok',   `API listening on ${color(`http://localhost:${PORT}`, C.brightCyan)}`);
    log('info', `Node        → ${color(process.version, C.brightGreen)}`);
    log('info', `Platform    → ${color(os.platform(), C.brightYellow)}`);
    log('info', `Architecture→ ${color(os.arch(), C.brightMagenta)}`);
    log('info', `Database    → PostgreSQL`);
    log('info', `Queue       → RabbitMQ`);
    divider();

    app.listen(PORT);
}

start().catch(err => {
    console.error(err);
    log('error', 'Fatal startup error');
    process.exit(1);
});