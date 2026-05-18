const cors = require('cors')
const express    = require('express');
const amqplib    = require('amqplib');
const { v4: uuidv4 } = require('uuid');
const { Pool }   = require('pg');
const bcrypt     = require('bcrypt');
const jwt        = require('jsonwebtoken');

const app = express();
app.use(express.json());


app.use(cors())

const JWT_SECRET = 'simux_secret_change_in_prod';

// ─── DB pool ─────────────────────────────────────────────────────────────────
const pool = new Pool({
    host:     'localhost',
    database: 'judgedb',
    user:     'judge',
    password: 'judge123',
    port:     5432,
});

// ─── RabbitMQ channel ────────────────────────────────────────────────────────
let channel = null;
async function getChannel() {
    if (channel) return channel;
    const conn = await amqplib.connect({
        protocol: 'amqp',
        hostname: 'localhost',
        username: 'admin',
        password: 'admin123',
    });
    channel = await conn.createChannel();
    await channel.assertQueue('submissions', { durable: true });
    return channel;
}

// ─── Auth middleware ──────────────────────────────────────────────────────────
function requireAuth(req, res, next) {
    const header = req.headers['authorization'];
    if (!header) return res.status(401).json({ error: 'no token' });

    const token = header.split(' ')[1]; // Bearer <token>
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

// ─── POST /register ───────────────────────────────────────────────────────────
app.post('/register', async (req, res) => {
    const { username, email, password } = req.body;
    if (!username || !email || !password)
        return res.status(400).json({ error: 'username, email, password required' });

    try {
        const hash = await bcrypt.hash(password, 10);
        const result = await pool.query(
            `INSERT INTO users (username, email, password)
             VALUES ($1, $2, $3) RETURNING id, username, role`,
            [username, email, hash]
        );
        res.json(result.rows[0]);
    } catch (err) {
        if (err.code === '23505')
            return res.status(409).json({ error: 'username or email already taken' });
        console.error(err);
        res.status(500).json({ error: 'db error' });
    }
});

// ─── POST /login ──────────────────────────────────────────────────────────────
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
        res.json({ token, username: user.username, role: user.role });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'db error' });
    }
});

// ─── GET /problems ────────────────────────────────────────────────────────────
app.get('/problems', async (req, res) => {
    try {
        const result = await pool.query(
            `SELECT id, slug, title, difficulty, time_limit, mem_limit, created_at
             FROM problems ORDER BY id ASC`
        );
        res.json(result.rows);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'db error' });
    }
});

// ─── GET /problems/:slug ──────────────────────────────────────────────────────
app.get('/problems/:slug', async (req, res) => {
    try {
        const prob = await pool.query(
            `SELECT id, slug, title, description, difficulty, time_limit, mem_limit
             FROM problems WHERE slug = $1`,
            [req.params.slug]
        );
        if (prob.rows.length === 0)
            return res.status(404).json({ error: 'problem not found' });

        const samples = await pool.query(
            `SELECT input, expected_output FROM test_cases
             WHERE problem_id = $1 AND is_sample = TRUE`,
            [prob.rows[0].id]
        );
        res.json({ ...prob.rows[0], sample_cases: samples.rows });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'db error' });
    }
});

// ─── POST /problems (admin only) ──────────────────────────────────────────────
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
        res.json({ id: problem_id, slug });
    } catch (err) {
        await client.query('ROLLBACK');
        console.error(err);
        res.status(500).json({ error: err.detail || 'db error' });
    } finally {
        client.release();
    }
});

// ─── POST /submit (auth required) ────────────────────────────────────────────
app.post('/submit', requireAuth, async (req, res) => {
    const { problem_slug, language, code } = req.body;
    if (!problem_slug || !language || !code)
        return res.status(400).json({ error: 'problem_slug, language, code required' });

    const SUPPORTED = ['python', 'c', 'cpp', 'java', 'javascript', 'rust'];
    if (!SUPPORTED.includes(language))
        return res.status(400).json({ error: `unsupported language: ${language}` });

    try {
        const prob = await pool.query(
            `SELECT id FROM problems WHERE slug = $1`, [problem_slug]
        );
        if (prob.rows.length === 0)
            return res.status(404).json({ error: 'problem not found' });

        const problem_id = prob.rows[0].id;

        const tcs = await pool.query(
            `SELECT input, expected_output FROM test_cases
             WHERE problem_id = $1 ORDER BY id ASC`,
            [problem_id]
        );
        if (tcs.rows.length === 0)
            return res.status(400).json({ error: 'problem has no test cases' });

        const test_cases = tcs.rows.map(r => ({
            input:           r.input,
            expected_output: r.expected_output,
        }));

        const id = uuidv4();

        await pool.query(
            `INSERT INTO submissions (id, language, code, status, problem_id, user_id)
             VALUES ($1, $2, $3, 'pending', $4, $5)`,
            [id, language, code, problem_id, req.user.id]
        );

        const ch = await getChannel();
        ch.sendToQueue(
            'submissions',
            Buffer.from(JSON.stringify({ id, language, code, test_cases })),
            { persistent: true }
        );

        res.json({ id });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'server error' });
    }
});

// ─── GET /verdict/:id ────────────────────────────────────────────────────────
app.get('/verdict/:id', async (req, res) => {
    try {
        const result = await pool.query(
            `SELECT id, language, status, verdict, time_ms, problem_id, created_at
             FROM submissions WHERE id = $1`,
            [req.params.id]
        );
        if (result.rows.length === 0)
            return res.status(404).json({ error: 'submission not found' });
        res.json(result.rows[0]);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'db error' });
    }
});

app.listen(3000, () => console.log('API running on :3000'));