import { useState } from "react";
import {
  BarChart, Bar, AreaChart, Area,
  XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, PieChart, Pie, Cell
} from "recharts";

// ─── Design tokens ──────────────────────────────────────────────────────────
const D = {
  bg:           '#080808',
  surface:      '#101010',
  card:         '#181818',
  border:       '#242424',
  orange:       '#E8531C',
  orangeGlow:   'rgba(232,83,28,0.09)',
  orangeBorder: 'rgba(232,83,28,0.28)',
  text:         '#EFEFEF',
  muted:        '#6B7280',
  dim:          '#9CA3AF',
  green:        '#34D399',
  red:          '#F87171',
  yellow:       '#FBBF24',
  blue:         '#60A5FA',
  purple:       '#A78BFA',
};

const mono = { fontFamily: "'Courier New', Courier, monospace" };

// ─── Atoms ──────────────────────────────────────────────────────────────────

function Tag({ children, color = D.orange }) {
  return (
    <span style={{
      background: `${color}18`, color,
      border: `1px solid ${color}30`,
      borderRadius: 4, padding: '2px 7px',
      fontSize: 11, fontWeight: 500,
      ...mono, letterSpacing: 0.3, whiteSpace: 'nowrap',
    }}>{children}</span>
  );
}

function Btn({ children, onClick, variant = 'primary', small, style: sx = {} }) {
  const pad = small ? '5px 11px' : '8px 18px';
  const fs  = small ? 12 : 13;
  const map = {
    primary: { background: D.orange,  color: '#fff',  border: 'none' },
    ghost:   { background: 'transparent', color: D.muted, border: `1px solid ${D.border}` },
    danger:  { background: `${D.red}18`, color: D.red, border: `1px solid ${D.red}30` },
  };
  return (
    <button onClick={onClick} style={{
      ...map[variant], borderRadius: 6, padding: pad, fontSize: fs,
      fontWeight: 500, cursor: 'pointer', fontFamily: 'inherit', ...sx,
    }}>{children}</button>
  );
}

function Card({ children, style: sx = {}, onClick }) {
  return (
    <div onClick={onClick} style={{
      background: D.card, border: `1px solid ${D.border}`,
      borderRadius: 10, padding: '16px 18px',
      cursor: onClick ? 'pointer' : undefined, ...sx,
    }}>{children}</div>
  );
}

function Stat({ label, value, sub, color = D.orange }) {
  return (
    <Card>
      <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 600, color, lineHeight: 1.1, marginBottom: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: D.muted }}>{sub}</div>}
    </Card>
  );
}

function Avatar({ name, color = D.orange, size = 34, stuck }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%', flexShrink: 0,
      background: stuck ? `${D.red}18` : D.orangeGlow,
      border: `1px solid ${stuck ? D.red + '50' : D.orangeBorder}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: size * 0.38, fontWeight: 600,
      color: stuck ? D.red : D.orange,
    }}>{name[0]}</div>
  );
}

function ProgressBar({ pct }) {
  const bg = pct > 75 ? D.green : pct > 50 ? D.orange : D.red;
  return (
    <div>
      <div style={{ fontSize: 10, color: D.muted, marginBottom: 3 }}>Progress {pct}%</div>
      <div style={{ height: 3, background: D.border, borderRadius: 2, overflow: 'hidden', width: 90 }}>
        <div style={{ width: `${pct}%`, height: '100%', background: bg }} />
      </div>
    </div>
  );
}

// ─── Top navigation bar ─────────────────────────────────────────────────────

function TopBar({ view, onNavigate }) {
  return (
    <div style={{
      height: 48, background: D.bg, borderBottom: `1px solid ${D.border}`,
      display: 'flex', alignItems: 'center', padding: '0 20px',
      justifyContent: 'space-between', flexShrink: 0,
    }}>
      <button onClick={() => onNavigate('landing')} style={{
        background: 'none', border: 'none', cursor: 'pointer',
        display: 'flex', alignItems: 'center', gap: 8, padding: 0,
      }}>
        <span style={{ ...mono, fontSize: 15, fontWeight: 700, color: D.text }}>
          codingrabbit<span style={{ color: D.orange }}>.dev</span>
        </span>
        <span style={{ fontSize: 14 }}>🐇</span>
      </button>

      {view !== 'landing' && (
        <div style={{ display: 'flex', gap: 5 }}>
          {[
            { v: 'admin',     label: 'Admin' },
            { v: 'professor', label: 'Professor' },
            { v: 'student',   label: 'Student' },
          ].map(({ v, label }) => (
            <button key={v} onClick={() => onNavigate(v)} style={{
              background: view === v ? D.orangeGlow : 'transparent',
              border: `1px solid ${view === v ? D.orangeBorder : D.border}`,
              color: view === v ? D.orange : D.muted,
              borderRadius: 6, padding: '4px 11px', cursor: 'pointer',
              fontSize: 12, fontWeight: view === v ? 500 : 400,
            }}>{label}</button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Shared sidebar ─────────────────────────────────────────────────────────

function Sidebar({ tabs, active, onTab, footer }) {
  return (
    <div style={{
      width: 208, borderRight: `1px solid ${D.border}`, background: D.surface,
      padding: '14px 10px', display: 'flex', flexDirection: 'column', flexShrink: 0,
    }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => onTab(t.key)} style={{
            background: active === t.key ? D.orangeGlow : 'transparent',
            border: `1px solid ${active === t.key ? D.orangeBorder : 'transparent'}`,
            color: active === t.key ? D.orange : D.muted,
            borderRadius: 7, padding: '9px 11px', cursor: 'pointer',
            textAlign: 'left', fontSize: 13,
            fontWeight: active === t.key ? 500 : 400,
            display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <span style={{ fontSize: 14 }}>{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </div>
      <div style={{ flex: 1 }} />
      {footer}
    </div>
  );
}

// recharts shared tooltip style
const TT = {
  contentStyle: {
    background: '#181818', border: '1px solid #242424',
    borderRadius: 6, fontSize: 12, color: '#EFEFEF',
  },
  labelStyle: { color: '#9CA3AF' },
};

// ════════════════════════════════════════════════════════════════════════════
// 1. LANDING PAGE
// ════════════════════════════════════════════════════════════════════════════

function LandingPage({ onNavigate }) {
  const [hover, setHover] = useState(null);

  return (
    <div style={{
      background: D.bg, color: D.text, fontFamily: 'system-ui, sans-serif',
      minHeight: '100vh', overflowY: 'auto',
    }}>
      {/* Navbar */}
      <nav style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 48px', height: 60, borderBottom: `1px solid ${D.border}`,
        position: 'sticky', top: 0, background: D.bg, zIndex: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ ...mono, fontSize: 18, fontWeight: 700 }}>
            codingrabbit<span style={{ color: D.orange }}>.dev</span>
          </span>
          <span style={{ fontSize: 16 }}>🐇</span>
          <Tag>Beta</Tag>
        </div>
        <Btn onClick={() => onNavigate('admin')}>Login →</Btn>
      </nav>

      {/* Hero */}
      <section style={{ padding: '68px 48px 52px', maxWidth: 980, margin: '0 auto', textAlign: 'center' }}>
        <div style={{ marginBottom: 18 }}>
          <Tag>Socratic AI Tutor · CS Education · Phase 1</Tag>
        </div>

        <h1 style={{
          fontSize: 52, fontWeight: 700, margin: '0 0 16px', lineHeight: 1.1,
          letterSpacing: -1.5, color: D.text,
        }}>
          The AI tutor that <span style={{ color: D.orange }}>asks</span><br />
          before it answers.
        </h1>
        <p style={{ color: D.muted, fontSize: 16, lineHeight: 1.8, maxWidth: 540, margin: '0 auto 48px' }}>
          CodingRabbit watches your code, detects where you're stuck, and leads
          you to the answer with questions — never handouts. Built for C++ courses,
          backed by your professor's approved material.
        </p>

        {/* Terminal hero block */}
        <div style={{
          background: D.surface, border: `1px solid ${D.border}`,
          borderRadius: 12, overflow: 'hidden', textAlign: 'left',
          marginBottom: 48, maxWidth: 780, margin: '0 auto 48px',
        }}>
          {/* Traffic lights */}
          <div style={{
            background: D.card, padding: '9px 14px',
            borderBottom: `1px solid ${D.border}`,
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            {[D.red, D.yellow, D.green].map((c, i) => (
              <div key={i} style={{ width: 10, height: 10, borderRadius: '50%', background: c }} />
            ))}
            <span style={{ ...mono, fontSize: 11, color: D.muted, marginLeft: 10 }}>
              session@codingrabbit:~/cs101 — bash
            </span>
          </div>

          {/* Body */}
          <div style={{ padding: '22px 28px', display: 'flex', gap: 36 }}>
            {/* ASCII rabbit */}
            <pre style={{
              ...mono, fontSize: 13, lineHeight: 1.58, margin: 0,
              color: D.text, flexShrink: 0,
            }}>{`
  /\\_/\\
 ( ^.^ )   "Don't panic."
  > 🥕 <
 /|   |\\   I'm CodeRabbit.
   | |
   |_|     I won't give
           you the answer.

           But I'll help
           you find it.`}</pre>

            {/* Simulated C++ code */}
            <div style={{ flex: 1, ...mono, fontSize: 12.5, lineHeight: 1.65 }}>
              <div style={{ color: D.muted, marginBottom: 10 }}>
                <span style={{ color: D.orange }}>$ </span>./codingrabbit --attach main.cpp
              </div>
              <div>
                <span style={{ color: D.blue }}>#include </span>
                <span style={{ color: D.green }}>&lt;wisdom.h&gt;</span><br />
                <span style={{ color: D.blue }}>#include </span>
                <span style={{ color: D.green }}>&lt;patience.h&gt;</span><br />
                <br />
                <span style={{ color: D.purple }}>int </span>
                <span style={{ color: D.text }}>learn</span>
                <span style={{ color: D.muted }}>(Student&amp; s) {'{'}</span><br />
                <span style={{ color: D.muted }}>{'  '}</span>
                <span style={{ color: D.blue }}>while </span>
                <span style={{ color: D.muted }}>(s.confused()) {'{'}</span><br />
                <span style={{ color: D.dim }}>{'    '}s.question = </span>
                <span style={{ color: D.orange }}>rabbit.ask</span>
                <span style={{ color: D.muted }}>(s.code);</span><br />
                <span style={{ color: '#4B5563' }}>{'    '}s.think();  // ← most important step</span><br />
                <span style={{ color: D.muted }}>{'  }'}</span><br />
                <span style={{ color: D.blue }}>{'  '}return </span>
                <span style={{ color: D.text }}>s.understanding;</span><br />
                <span style={{ color: D.muted }}>{'}'}</span>
              </div>
              <div style={{ marginTop: 14, color: D.green, fontSize: 12 }}>
                ✓ Attached · monitoring for errors and confusion signals...
              </div>
            </div>
          </div>
        </div>

        {/* Role preview buttons */}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
          {[
            { label: 'Student interface',   view: 'student',   desc: 'Monaco editor + AI chat' },
            { label: 'Professor dashboard', view: 'professor', desc: 'Class & material management' },
            { label: 'Admin panel',         view: 'admin',     desc: 'Models, RAG, users, courses' },
          ].map(r => (
            <button key={r.view}
              onClick={() => onNavigate(r.view)}
              onMouseEnter={() => setHover(r.view)}
              onMouseLeave={() => setHover(null)}
              style={{
                background: hover === r.view ? D.orangeGlow : 'transparent',
                border: `1px solid ${hover === r.view ? D.orangeBorder : D.border}`,
                borderRadius: 8, padding: '12px 22px', cursor: 'pointer',
                textAlign: 'left', transition: 'all 0.15s',
              }}>
              <div style={{ color: hover === r.view ? D.orange : D.text, fontWeight: 500, fontSize: 13 }}>
                → {r.label}
              </div>
              <div style={{ color: D.muted, fontSize: 11, marginTop: 3 }}>{r.desc}</div>
            </button>
          ))}
        </div>
      </section>

      {/* Feature cards */}
      <section style={{ padding: '8px 48px 80px', maxWidth: 980, margin: '0 auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
          {[
            {
              icon: '🤔', tag: 'Core Method', tc: D.orange,
              title: 'Socratic, not prescriptive',
              desc: 'CodeRabbit reads your code and compiler errors, then asks guided questions until the insight is yours — not handed to you.',
            },
            {
              icon: '📊', tag: 'For Professors', tc: D.blue,
              title: 'Live class insight',
              desc: 'See exactly where your class gets stuck, who\'s ahead, which concepts need re-teaching — all in one dashboard.',
            },
            {
              icon: '🔒', tag: 'Curriculum-gated', tc: D.green,
              title: 'No leaking ahead',
              desc: 'The AI only accesses material your professor has approved and released. Week 3 stays locked until Week 3.',
            },
          ].map(f => (
            <Card key={f.title} style={{ padding: '20px 18px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                <span style={{ fontSize: 20 }}>{f.icon}</span>
                <Tag color={f.tc}>{f.tag}</Tag>
              </div>
              <div style={{ fontWeight: 500, fontSize: 14, marginBottom: 8 }}>{f.title}</div>
              <div style={{ color: D.muted, fontSize: 13, lineHeight: 1.65 }}>{f.desc}</div>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// 2. ADMIN DASHBOARD
// ════════════════════════════════════════════════════════════════════════════

function AdminDashboard({ onNavigate }) {
  const [tab, setTab] = useState('stats');

  const sessionData = [
    { day: 'Mon', sessions: 142, resolved: 104 },
    { day: 'Tue', sessions: 189, resolved: 137 },
    { day: 'Wed', sessions: 211, resolved: 150 },
    { day: 'Thu', sessions: 167, resolved: 123 },
    { day: 'Fri', sessions: 98,  resolved: 69  },
    { day: 'Sat', sessions: 43,  resolved: 32  },
    { day: 'Sun', sessions: 57,  resolved: 42  },
  ];
  const modelShare = [
    { name: 'Sonnet', value: 78, color: D.orange },
    { name: 'Haiku',  value: 15, color: D.blue },
    { name: 'Opus',   value: 7,  color: D.green },
  ];
  const models = [
    { name: 'claude-sonnet-4-20250514', active: true,  tier: 'Balanced',    speed: 'Fast',    note: 'Recommended' },
    { name: 'claude-opus-4-20250514',   active: false, tier: 'Powerful',    speed: 'Slower',  note: 'High cost' },
    { name: 'claude-haiku-4-5',         active: false, tier: 'Lightweight', speed: 'Fastest', note: 'Budget' },
  ];
  const professors = [
    { name: 'Dr. Rivera', email: 'crivera@university.edu', courses: 3, students: 87, status: 'active' },
    { name: 'Prof. Kim',  email: 'jkim@university.edu',    courses: 2, students: 54, status: 'active' },
    { name: 'Dr. Patel',  email: 'rpatel@university.edu',  courses: 1, students: 30, status: 'invited' },
  ];
  const courses = [
    { code: 'CS101', name: 'Intro to C++',    prof: 'Dr. Rivera', students: 32, status: 'active' },
    { code: 'CS201', name: 'Data Structures', prof: 'Prof. Kim',  students: 28, status: 'active' },
    { code: 'CS301', name: 'Algorithms',      prof: 'Dr. Rivera', students: 27, status: 'draft' },
  ];
  const docs = [
    { name: 'CS101_Week1_Pointers.pdf',    course: 'CS101', size: '2.4 MB', status: 'indexed'  },
    { name: 'CS201_Trees_Lecture.pdf',     course: 'CS201', size: '1.8 MB', status: 'indexed'  },
    { name: 'CS101_Week3_OOP.pdf',         course: 'CS101', size: '3.1 MB', status: 'indexing' },
  ];

  const adminTabs = [
    { key: 'stats',   icon: '📊', label: 'Evaluation' },
    { key: 'models',  icon: '🤖', label: 'AI Models' },
    { key: 'rag',     icon: '📚', label: 'RAG Docs' },
    { key: 'users',   icon: '👥', label: 'Users' },
    { key: 'courses', icon: '🎓', label: 'Courses' },
  ];

  const footer = (
    <Card style={{ padding: '10px 12px', marginTop: 12, borderRadius: 8 }}>
      <div style={{ ...mono, fontSize: 11, color: D.green }}>● SYSTEM ONLINE</div>
      <div style={{ fontSize: 11, color: D.muted, marginTop: 3 }}>All services healthy</div>
    </Card>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: D.bg, color: D.text, fontFamily: 'system-ui, sans-serif' }}>
      <TopBar view="admin" onNavigate={onNavigate} />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <Sidebar tabs={adminTabs} active={tab} onTab={setTab} footer={footer} />

        <div style={{ flex: 1, overflow: 'auto', padding: 22 }}>

          {/* EVALUATION STATS */}
          {tab === 'stats' && (
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 18 }}>Evaluation dashboard</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
                <Stat label="// sessions.today"   value="211" sub="+18% from yesterday" />
                <Stat label="// hints.requested"  value="61"  sub="28.9% hint rate"      color={D.yellow} />
                <Stat label="// problems.solved"  value="150" sub="71% resolution rate"  color={D.green} />
                <Stat label="// avg.session_min"  value="24m" sub="↑ 3 min this week"    color={D.blue} />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '5fr 2fr', gap: 14 }}>
                <Card>
                  <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>// sessions_this_week</div>
                  <ResponsiveContainer width="100%" height={200}>
                    <AreaChart data={sessionData}>
                      <CartesianGrid strokeDasharray="3 3" stroke={D.border} />
                      <XAxis dataKey="day" stroke={D.muted} tick={{ fontSize: 11, fill: D.muted }} />
                      <YAxis stroke={D.muted} tick={{ fontSize: 11, fill: D.muted }} />
                      <Tooltip {...TT} />
                      <Area type="monotone" dataKey="sessions" stroke={D.orange} fill={`${D.orange}12`} strokeWidth={2} name="sessions" />
                      <Area type="monotone" dataKey="resolved" stroke={D.green}  fill={`${D.green}08`}  strokeWidth={2} name="resolved" />
                    </AreaChart>
                  </ResponsiveContainer>
                </Card>
                <Card>
                  <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>// model_share</div>
                  <ResponsiveContainer width="100%" height={130}>
                    <PieChart>
                      <Pie data={modelShare} cx="50%" cy="50%" outerRadius={54} dataKey="value" strokeWidth={0}>
                        {modelShare.map((m, i) => <Cell key={i} fill={m.color} />)}
                      </Pie>
                      <Tooltip {...TT} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
                    {modelShare.map(m => (
                      <div key={m.name} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
                        <div style={{ width: 7, height: 7, borderRadius: '50%', background: m.color, flexShrink: 0 }} />
                        <span style={{ color: D.dim, flex: 1 }}>{m.name}</span>
                        <span style={{ color: D.text, ...mono }}>{m.value}%</span>
                      </div>
                    ))}
                  </div>
                </Card>
              </div>
            </div>
          )}

          {/* AI MODELS */}
          {tab === 'models' && (
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 18 }}>AI model configuration</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
                {models.map(m => (
                  <Card key={m.name} style={{
                    display: 'flex', alignItems: 'center', gap: 16,
                    borderColor: m.active ? D.orangeBorder : D.border,
                    background: m.active ? `${D.orange}05` : D.card,
                  }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                        <span style={{ ...mono, fontSize: 13, fontWeight: 500 }}>{m.name}</span>
                        {m.active && <Tag>Active</Tag>}
                        <Tag color={D.muted}>{m.note}</Tag>
                      </div>
                      <div style={{ display: 'flex', gap: 18 }}>
                        {[['Tier', m.tier], ['Speed', m.speed]].map(([k, v]) => (
                          <span key={k} style={{ fontSize: 12, color: D.muted }}>
                            {k}: <span style={{ color: D.dim }}>{v}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                    <Btn variant={m.active ? 'ghost' : 'primary'} small>
                      {m.active ? '✓ Active' : 'Activate'}
                    </Btn>
                  </Card>
                ))}
              </div>
              <Card>
                <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>// guardrail_settings</div>
                {[
                  { label: 'Max hints per session',       val: '3' },
                  { label: 'Hint delay (stuck threshold)', val: '180s' },
                  { label: 'Socratic strictness',          val: 'Medium' },
                  { label: 'Allow code completion',        val: 'No' },
                ].map((g, i, arr) => (
                  <div key={g.label} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '9px 0',
                    borderBottom: i < arr.length - 1 ? `1px solid ${D.border}` : 'none',
                  }}>
                    <span style={{ fontSize: 13, color: D.dim }}>{g.label}</span>
                    <Tag color={D.blue}>{g.val}</Tag>
                  </div>
                ))}
              </Card>
            </div>
          )}

          {/* RAG DOCS */}
          {tab === 'rag' && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
                <div style={{ fontSize: 18, fontWeight: 600 }}>RAG document library</div>
                <Btn small>+ Upload document</Btn>
              </div>
              <div style={{
                border: `2px dashed ${D.border}`, borderRadius: 10,
                padding: 36, textAlign: 'center', marginBottom: 16,
              }}>
                <div style={{ fontSize: 24, marginBottom: 8 }}>📎</div>
                <div style={{ fontWeight: 500, fontSize: 14, marginBottom: 4 }}>Drop course materials here</div>
                <div style={{ color: D.muted, fontSize: 12 }}>PDF, DOCX, MD · up to 25 MB per file</div>
                <Btn style={{ marginTop: 14 }} small>Browse files</Btn>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {docs.map(d => (
                  <Card key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 16px' }}>
                    <span style={{ fontSize: 16, flexShrink: 0 }}>📄</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{d.name}</div>
                      <div style={{ fontSize: 11, color: D.muted, marginTop: 2 }}>{d.course} · {d.size}</div>
                    </div>
                    <Tag color={d.status === 'indexed' ? D.green : D.yellow}>
                      {d.status === 'indexed' ? '✓ indexed' : '⏳ indexing'}
                    </Tag>
                    <Btn variant="danger" small>Remove</Btn>
                  </Card>
                ))}
              </div>
            </div>
          )}

          {/* USERS */}
          {tab === 'users' && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <div style={{ fontSize: 18, fontWeight: 600 }}>Professors</div>
                <Btn small>+ Add professor</Btn>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 28 }}>
                {professors.map(p => (
                  <Card key={p.email} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 16px' }}>
                    <Avatar name={p.name.split(' ').pop()} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{p.name}</div>
                      <div style={{ fontSize: 11, color: D.muted }}>{p.email}</div>
                    </div>
                    <div style={{ textAlign: 'center', minWidth: 40 }}>
                      <div style={{ fontSize: 15, fontWeight: 600 }}>{p.courses}</div>
                      <div style={{ fontSize: 10, color: D.muted }}>courses</div>
                    </div>
                    <div style={{ textAlign: 'center', minWidth: 50 }}>
                      <div style={{ fontSize: 15, fontWeight: 600 }}>{p.students}</div>
                      <div style={{ fontSize: 10, color: D.muted }}>students</div>
                    </div>
                    <Tag color={p.status === 'active' ? D.green : D.yellow}>{p.status}</Tag>
                    <Btn variant="danger" small>Remove</Btn>
                  </Card>
                ))}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                <div style={{ fontSize: 18, fontWeight: 600 }}>Students</div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <Btn variant="ghost" small>Import CSV</Btn>
                  <Btn small>+ Invite student</Btn>
                </div>
              </div>
              <div style={{ ...mono, fontSize: 11, color: D.muted, padding: '8px 0' }}>
                // 116 students across 3 courses · invite-only registration
              </div>
            </div>
          )}

          {/* COURSES */}
          {tab === 'courses' && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
                <div style={{ fontSize: 18, fontWeight: 600 }}>Courses</div>
                <Btn small>+ Create course</Btn>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {courses.map(c => (
                  <Card key={c.code} style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                    <div style={{
                      background: D.orangeGlow, border: `1px solid ${D.orangeBorder}`,
                      borderRadius: 6, padding: '5px 11px',
                      ...mono, fontSize: 13, fontWeight: 600, color: D.orange, flexShrink: 0,
                    }}>{c.code}</div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 14, fontWeight: 500 }}>{c.name}</div>
                      <div style={{ fontSize: 12, color: D.muted, marginTop: 2 }}>Prof: {c.prof}</div>
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 15, fontWeight: 600 }}>{c.students}</div>
                      <div style={{ fontSize: 10, color: D.muted }}>students</div>
                    </div>
                    <Tag color={c.status === 'active' ? D.green : D.yellow}>{c.status}</Tag>
                    <Btn variant="ghost" small>Manage</Btn>
                  </Card>
                ))}
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// 3. PROFESSOR DASHBOARD
// ════════════════════════════════════════════════════════════════════════════

function ProfessorDashboard({ onNavigate }) {
  const [tab, setTab]         = useState('overview');
  const [monitorId, setMonitorId] = useState(null);

  const students = [
    { id: 's1', name: 'Alice Chen',    last: '2h ago',  sessions: 23, hints: 8,  progress: 85, stuck: false },
    { id: 's2', name: 'Bob Martinez',  last: '15m ago', sessions: 18, hints: 14, progress: 62, stuck: true  },
    { id: 's3', name: 'Carol Liu',     last: '1d ago',  sessions: 31, hints: 3,  progress: 94, stuck: false },
    { id: 's4', name: 'David Osei',    last: '3h ago',  sessions: 12, hints: 19, progress: 45, stuck: true  },
    { id: 's5', name: 'Emma Park',     last: '30m ago', sessions: 27, hints: 6,  progress: 78, stuck: false },
  ];

  const weekData = [
    { week: 'W1', sessions: 4, hints: 1 },
    { week: 'W2', sessions: 6, hints: 2 },
    { week: 'W3', sessions: 6, hints: 2 },
    { week: 'W4', sessions: 7, hints: 3 },
    { week: 'W5', sessions: 6, hints: 3 },
  ];

  const materials = [
    { week: 'Week 1: Pointers & References',     docs: 3, released: true },
    { week: 'Week 2: Arrays & Strings',          docs: 2, released: true },
    { week: 'Week 3: Classes & OOP',             docs: 4, released: false },
    { week: 'Week 4: Templates',                 docs: 0, released: false },
  ];

  const profTabs = [
    { key: 'overview',   icon: '📋', label: 'Overview' },
    { key: 'materials',  icon: '📚', label: 'Materials' },
    { key: 'students',   icon: '👥', label: 'Students' },
    { key: 'analytics',  icon: '📊', label: 'Analytics' },
  ];

  const monitored = students.find(s => s.id === monitorId);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: D.bg, color: D.text, fontFamily: 'system-ui, sans-serif' }}>
      <TopBar view="professor" onNavigate={onNavigate} />

      {/* Course selector */}
      <div style={{
        padding: '9px 20px', borderBottom: `1px solid ${D.border}`,
        display: 'flex', alignItems: 'center', gap: 14, background: D.surface,
      }}>
        <span style={{ fontSize: 13, color: D.muted }}>Teaching:</span>
        <select style={{
          background: D.card, border: `1px solid ${D.border}`, color: D.text,
          borderRadius: 6, padding: '5px 10px', fontSize: 13, cursor: 'pointer',
        }}>
          <option>CS101 — Intro to C++</option>
          <option>CS201 — Data Structures</option>
        </select>
        <div style={{ flex: 1 }} />
        <Tag color={D.green}>32 enrolled</Tag>
        <Tag color={D.red}>2 stuck now</Tag>
      </div>

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <Sidebar tabs={profTabs} active={monitorId ? null : tab} onTab={t => { setTab(t); setMonitorId(null); }} />

        <div style={{ flex: 1, overflow: 'auto', padding: 22 }}>

          {/* MONITOR STUDENT (detail overlay) */}
          {monitorId && monitored ? (
            <div>
              <button onClick={() => setMonitorId(null)} style={{
                background: 'none', border: 'none', color: D.orange, cursor: 'pointer',
                fontSize: 13, display: 'flex', alignItems: 'center', gap: 4,
                marginBottom: 18, padding: 0,
              }}>
                ← Back to students
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
                <Avatar name={monitored.name} size={38} stuck={monitored.stuck} />
                <div style={{ fontSize: 17, fontWeight: 600 }}>{monitored.name}</div>
                {monitored.stuck && <Tag color={D.red}>🔴 Stuck</Tag>}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 18 }}>
                <Stat label="// total_sessions"   value={monitored.sessions}          sub="all time" />
                <Stat label="// hints_used"        value={monitored.hints}             sub="this course" color={D.yellow} />
                <Stat label="// curriculum_done"   value={`${monitored.progress}%`}   sub="of Week 2" color={D.green} />
              </div>
              <Card>
                <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>// recent_activity_log</div>
                {[
                  { t: '15m', msg: 'Opened linked_list.cpp — working on insert()',           type: 'code' },
                  { t: '18m', msg: 'Compiler error: "use of undeclared identifier \'next\'"', type: 'error' },
                  { t: '20m', msg: 'Hint requested — null pointer check on line 34',          type: 'hint' },
                  { t: '35m', msg: 'Session started — CS101 Week 2 assignment',               type: 'info' },
                ].map((e, i, arr) => (
                  <div key={i} style={{
                    display: 'flex', gap: 14, padding: '8px 0', alignItems: 'flex-start',
                    borderBottom: i < arr.length - 1 ? `1px solid ${D.border}` : 'none',
                  }}>
                    <span style={{ ...mono, fontSize: 10, color: D.muted, width: 30, flexShrink: 0 }}>{e.t}m</span>
                    <span style={{
                      fontSize: 12, lineHeight: 1.5,
                      color: e.type === 'error' ? D.red : e.type === 'hint' ? D.yellow : D.dim,
                    }}>{e.msg}</span>
                  </div>
                ))}
              </Card>
            </div>

          ) : tab === 'overview' ? (
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 18 }}>CS101 — overview</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
                <Stat label="// enrolled"       value="32"  sub="students" />
                <Stat label="// avg_progress"   value="71%" sub="curriculum"     color={D.green} />
                <Stat label="// stuck_now"      value="2"   sub="need attention" color={D.red} />
                <Stat label="// sessions_week"  value="89"  sub="this week"      color={D.blue} />
              </div>
              <Card>
                <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>// top_struggle_points</div>
                {[
                  { label: 'Pointer arithmetic (Week 1)',            pct: 85 },
                  { label: 'Dynamic memory · new & delete (Week 2)', pct: 62 },
                  { label: 'Class constructors & destructors (W3)',   pct: 38 },
                ].map((s, i, arr) => (
                  <div key={s.label} style={{
                    display: 'flex', alignItems: 'center', gap: 12, padding: '9px 0',
                    borderBottom: i < arr.length - 1 ? `1px solid ${D.border}` : 'none',
                  }}>
                    <span style={{ ...mono, color: D.muted, fontSize: 11, width: 20 }}>#{i + 1}</span>
                    <span style={{ flex: 1, fontSize: 13 }}>{s.label}</span>
                    <div style={{ width: 80, height: 4, background: D.border, borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{ width: `${s.pct}%`, height: '100%', background: D.orange }} />
                    </div>
                    <span style={{ ...mono, fontSize: 11, color: D.muted, width: 32, textAlign: 'right' }}>{s.pct}%</span>
                  </div>
                ))}
              </Card>
            </div>

          ) : tab === 'materials' ? (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
                <div style={{ fontSize: 18, fontWeight: 600 }}>Course materials</div>
                <Btn small>+ Upload document</Btn>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {materials.map(m => (
                  <Card key={m.week} style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 3 }}>{m.week}</div>
                      <div style={{ fontSize: 11, color: D.muted }}>{m.docs} document{m.docs !== 1 ? 's' : ''} uploaded</div>
                    </div>
                    <Tag color={m.released ? D.green : D.muted}>
                      {m.released ? '✓ Released' : 'Unreleased'}
                    </Tag>
                    <Btn variant="ghost" small>Upload +</Btn>
                    {!m.released && <Btn small>Release</Btn>}
                  </Card>
                ))}
              </div>
            </div>

          ) : tab === 'students' ? (
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 18 }}>Students — CS101</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {students.map(s => (
                  <Card key={s.id} onClick={() => setMonitorId(s.id)} style={{
                    display: 'flex', alignItems: 'center', gap: 14,
                    borderColor: s.stuck ? `${D.red}40` : D.border,
                    background: s.stuck ? `${D.red}06` : D.card,
                  }}>
                    <Avatar name={s.name} stuck={s.stuck} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{s.name}</div>
                      <div style={{ fontSize: 11, color: D.muted }}>Last active: {s.last}</div>
                    </div>
                    <ProgressBar pct={s.progress} />
                    <div style={{ textAlign: 'center', width: 40 }}>
                      <div style={{ fontSize: 14, fontWeight: 600 }}>{s.hints}</div>
                      <div style={{ fontSize: 10, color: D.muted }}>hints</div>
                    </div>
                    {s.stuck && <Tag color={D.red}>🔴 Stuck</Tag>}
                    <span style={{ color: D.muted, fontSize: 16 }}>›</span>
                  </Card>
                ))}
              </div>
            </div>

          ) : tab === 'analytics' ? (
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 18 }}>Class analytics</div>
              <Card>
                <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>// avg_sessions_and_hints_per_week</div>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={weekData}>
                    <CartesianGrid strokeDasharray="3 3" stroke={D.border} />
                    <XAxis dataKey="week" stroke={D.muted} tick={{ fontSize: 11, fill: D.muted }} />
                    <YAxis stroke={D.muted} tick={{ fontSize: 11, fill: D.muted }} />
                    <Tooltip {...TT} />
                    <Bar dataKey="sessions" fill={D.orange} radius={[3, 3, 0, 0]} name="avg sessions" />
                    <Bar dataKey="hints"    fill={D.yellow} radius={[3, 3, 0, 0]} name="avg hints" />
                  </BarChart>
                </ResponsiveContainer>
              </Card>
            </div>
          ) : null}

        </div>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// 4. STUDENT INTERFACE
// ════════════════════════════════════════════════════════════════════════════

function StudentInterface({ onNavigate }) {
  const [messages, setMessages] = useState([
    { role: 'bot',  content: "Hey! I can see you're working on `linked_list.cpp`. What are you trying to do right now?" },
    { role: 'user', content: "I'm trying to implement insert() but I keep getting a segfault." },
    { role: 'bot',  content: "Segfaults in linked list inserts almost always come from one of two places — and finding it yourself will stick.\n\nLet me ask: the very first time you call insert() on a brand-new list, what is the value of this->head?" },
    { role: 'user', content: "It's... whatever was in memory? I didn't set it to anything." },
    { role: 'bot',  content: "Exactly. And on line 19 you do `head->next` — what happens when you dereference a pointer that was never initialized?\n\nWhat should head be set to when the list is brand new and empty?" },
  ]);
  const [input, setInput] = useState('');

  const send = () => {
    if (!input.trim()) return;
    const msg = input;
    setInput('');
    setMessages(m => [...m,
      { role: 'user', content: msg },
      { role: 'bot',  content: "Right! So the fix is a single character. Can you find the constructor on line 15 and make head point to something that means 'nothing here yet' in C++?" },
    ]);
  };

  // Code with syntax-like coloring data
  const lines = [
    { n:  1, text: '#include <iostream>',                                             fg: D.blue },
    { n:  2, text: 'using namespace std;',                                            fg: D.purple },
    { n:  3, text: '',                                                                 fg: D.dim },
    { n:  4, text: 'struct Node {',                                                   fg: D.text },
    { n:  5, text: '    int data;',                                                   fg: D.dim },
    { n:  6, text: '    Node* next;',                                                 fg: D.dim },
    { n:  7, text: '    Node(int v) : data(v), next(nullptr) {}',                    fg: D.dim },
    { n:  8, text: '};',                                                               fg: D.text },
    { n:  9, text: '',                                                                 fg: D.dim },
    { n: 10, text: 'class LinkedList {',                                              fg: D.text },
    { n: 11, text: 'private:',                                                        fg: D.purple },
    { n: 12, text: '    Node* head;',                                                 fg: D.dim },
    { n: 13, text: '',                                                                 fg: D.dim },
    { n: 14, text: 'public:',                                                         fg: D.purple },
    { n: 15, text: '    LinkedList() {}  // ← BUG: head never initialized',           fg: '#FCD34D', bg: `${D.yellow}0C`, borderLeft: `2px solid ${D.yellow}` },
    { n: 16, text: '',                                                                 fg: D.dim },
    { n: 17, text: '    void insert(int val) {',                                      fg: D.text },
    { n: 18, text: '        Node* newNode = new Node(val);',                          fg: D.dim },
    { n: 19, text: '        newNode->next = head->next;  // ← SEGFAULT HERE',        fg: '#FCA5A5', bg: `${D.red}14`, borderLeft: `2px solid ${D.red}` },
    { n: 20, text: '        head = newNode;',                                         fg: D.dim },
    { n: 21, text: '    }',                                                            fg: D.text },
    { n: 22, text: '',                                                                 fg: D.dim },
    { n: 23, text: '    void print() {',                                              fg: D.text },
    { n: 24, text: '        Node* curr = head;',                                      fg: D.dim },
    { n: 25, text: '        while (curr != nullptr) {',                               fg: D.dim },
    { n: 26, text: '            cout << curr->data << " -> ";',                       fg: D.dim },
    { n: 27, text: '            curr = curr->next;',                                  fg: D.dim },
    { n: 28, text: '        }',                                                        fg: D.dim },
    { n: 29, text: '        cout << "NULL" << endl;',                                 fg: D.dim },
    { n: 30, text: '    }',                                                            fg: D.text },
    { n: 31, text: '};',                                                               fg: D.text },
    { n: 32, text: '',                                                                 fg: D.dim },
    { n: 33, text: 'int main() {',                                                    fg: D.text },
    { n: 34, text: '    LinkedList list;',                                            fg: D.dim },
    { n: 35, text: '    list.insert(1);  // ← crashes here',                        fg: '#FCA5A5', bg: `${D.red}0A`, borderLeft: `2px solid transparent` },
    { n: 36, text: '    list.insert(2);',                                             fg: D.dim },
    { n: 37, text: '    list.print();',                                               fg: D.dim },
    { n: 38, text: '    return 0;',                                                   fg: D.dim },
    { n: 39, text: '}',                                                                fg: D.text },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: D.bg, color: D.text, fontFamily: 'system-ui, sans-serif' }}>
      <TopBar view="student" onNavigate={onNavigate} />

      {/* IDE chrome bar */}
      <div style={{
        padding: '5px 16px', borderBottom: `1px solid ${D.border}`,
        display: 'flex', alignItems: 'center', gap: 12, background: '#1a1a1a',
      }}>
        <Tag>CS101</Tag>
        <span style={{ ...mono, fontSize: 12, color: D.text }}>linked_list.cpp</span>
        <span style={{ ...mono, fontSize: 11, color: D.red }}>● 1 error</span>
        <span style={{ ...mono, fontSize: 11, color: D.yellow }}>▲ 1 warning</span>
        <div style={{ flex: 1 }} />
        <span style={{ ...mono, fontSize: 10, color: D.muted }}>Week 2 · Dynamic memory · C++17</span>
      </div>

      {/* Split pane */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

        {/* Monaco-style editor */}
        <div style={{ flex: 3, background: '#1e1e1e', overflow: 'auto', borderRight: `1px solid #111` }}>
          {/* Tab bar */}
          <div style={{ background: '#252526', borderBottom: '1px solid #1a1a1a', display: 'flex' }}>
            {['linked_list.cpp', 'main.cpp'].map((f, i) => (
              <div key={f} style={{
                padding: '5px 16px', fontSize: 12, cursor: 'pointer',
                color: i === 0 ? '#ccc' : '#666',
                background: i === 0 ? '#1e1e1e' : '#2d2d2d',
                borderRight: '1px solid #1a1a1a',
                ...mono,
              }}>
                {i === 0 && <span style={{ color: D.red, marginRight: 4 }}>●</span>}
                {f}
              </div>
            ))}
          </div>

          {/* Lines */}
          <div style={{ padding: '8px 0', ...mono, fontSize: 12.5, lineHeight: 1.65 }}>
            {lines.map(l => (
              <div key={l.n} style={{
                display: 'flex', background: l.bg || 'transparent',
                borderLeft: l.borderLeft || '2px solid transparent',
              }}>
                <span style={{
                  width: 44, textAlign: 'right', paddingRight: 16,
                  color: '#3d3d3d', fontSize: 11, userSelect: 'none', flexShrink: 0,
                }}>{l.n}</span>
                <span style={{ color: l.fg, whiteSpace: 'pre' }}>{l.text}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Chat panel */}
        <div style={{ flex: 2, display: 'flex', flexDirection: 'column', background: D.bg, minWidth: 0 }}>
          {/* Header */}
          <div style={{
            padding: '10px 14px', borderBottom: `1px solid ${D.border}`,
            display: 'flex', alignItems: 'center', gap: 8, background: D.surface,
          }}>
            <span style={{ fontSize: 16 }}>🐇</span>
            <span style={{ fontWeight: 500, fontSize: 14, ...mono }}>CodeRabbit</span>
            <div style={{ width: 6, height: 6, background: D.green, borderRadius: '50%' }} />
            <div style={{ flex: 1 }} />
            <span style={{ ...mono, fontSize: 10, color: D.muted }}>linked_list.cpp ✓</span>
          </div>

          {/* Messages */}
          <div style={{
            flex: 1, overflow: 'auto', padding: '14px',
            display: 'flex', flexDirection: 'column', gap: 10,
          }}>
            {messages.map((m, i) => (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
                {m.role === 'bot' && (
                  <span style={{ fontSize: 10, color: D.muted, marginBottom: 3, ...mono }}>🐇 codingrabbit</span>
                )}
                <div style={{
                  maxWidth: '90%', padding: '9px 13px',
                  borderRadius: m.role === 'user' ? '12px 12px 3px 12px' : '12px 12px 12px 3px',
                  background: m.role === 'user' ? D.orange : D.card,
                  border: m.role === 'user' ? 'none' : `1px solid ${D.border}`,
                  color: D.text, fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-line',
                }}>{m.content}</div>
              </div>
            ))}
          </div>

          {/* Input */}
          <div style={{
            padding: '10px 14px', borderTop: `1px solid ${D.border}`,
            display: 'flex', gap: 8, alignItems: 'flex-end',
          }}>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="Ask CodeRabbit… (Enter to send)"
              rows={1}
              style={{
                flex: 1, background: D.card, border: `1px solid ${D.border}`,
                color: D.text, borderRadius: 8, padding: '8px 11px',
                fontSize: 13, resize: 'none', fontFamily: 'system-ui',
                lineHeight: 1.5, outline: 'none', maxHeight: 100,
              }}
            />
            <Btn onClick={send} style={{ padding: '8px 14px', flexShrink: 0 }}>Send</Btn>
          </div>
        </div>

      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// ROOT
// ════════════════════════════════════════════════════════════════════════════

export default function App() {
  const [view, setView] = useState('landing');
  return view === 'admin'
    ? <AdminDashboard     onNavigate={setView} />
    : view === 'professor'
    ? <ProfessorDashboard onNavigate={setView} />
    : view === 'student'
    ? <StudentInterface   onNavigate={setView} />
    : <LandingPage        onNavigate={setView} />;
}
