import { useState } from 'react';
import {
  XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer,
  BarChart, Bar, Legend,
  ScatterChart, Scatter, ZAxis
} from 'recharts';
import { Card } from '../../design/atoms';
import { D } from '../../design/tokens';
import type {
  AnalyticsCognitiveProgressionPoint,
  AnalyticsTimeUtilizationPoint,
  AnalyticsPedagogicalActionPoint,
  AnalyticsFrustrationPoint
} from '../../api/professorSectionsApi';

interface ProfessorAnalyticsChartsProps {
  cognitive_progression: AnalyticsCognitiveProgressionPoint[];
  pedagogical_actions: AnalyticsPedagogicalActionPoint[];
  frustration_by_week: AnalyticsFrustrationPoint[];
  time_utilization: AnalyticsTimeUtilizationPoint[];
}

const renderHeatmapRect = (props: { cx?: number; cy?: number; payload?: { count?: number; Count?: number } }, maxVal: number, baseColor: string) => {
  const { cx = 0, cy = 0, payload } = props;
  const count = payload?.count ?? payload?.Count ?? 0;
  if (!payload || count === 0) return null;

  const intensity = Math.max(0.1, count / maxVal);
  const rectWidth = 45;
  const rectHeight = 35;
  return (
    <rect
      x={cx - rectWidth / 2}
      y={cy - rectHeight / 2}
      width={rectWidth}
      height={rectHeight}
      fill={baseColor}
      fillOpacity={intensity}
      rx={4}
      ry={4}
    />
  );
};

export function ProfessorAnalyticsCharts({
  cognitive_progression,
  pedagogical_actions,
  frustration_by_week,
  time_utilization,
}: ProfessorAnalyticsChartsProps) {
  const [activeTab, setActiveTab] = useState<'homework' | 'study'>('homework');

  const HOMEWORK_SCAFFOLDS = ["Conceptual Hint", "Direct Syntax Scaffold", "Visual Scaffold"];
  const STUDY_SCAFFOLDS = ["Conceptual Integration", "Analogy Scaffold", "Direct Theory Scaffold"];

  const homeworkActions = pedagogical_actions.filter(d => HOMEWORK_SCAFFOLDS.includes(d.scaffold_name));
  const studyActions = pedagogical_actions.filter(d => STUDY_SCAFFOLDS.includes(d.scaffold_name));
  const activeActions = activeTab === 'homework' ? homeworkActions : studyActions;

  const ALL_COGNITIVE_STAGES = ["Conceptualizing", "Implementing", "Refactoring", "Debugging"];
  const firstWeek = cognitive_progression.length > 0 ? cognitive_progression[0].x.replace('Week ', '') : "1";

  const augmentedCognitiveProgression = cognitive_progression.map(d => ({
    Week: d.x.replace('Week ', ''),
    Stage: d.stage_name,
    Count: d.count
  }));

  for (const stage of ALL_COGNITIVE_STAGES) {
    if (!augmentedCognitiveProgression.some(d => d.Stage === stage)) {
      augmentedCognitiveProgression.push({ Week: firstWeek, Stage: stage, Count: 0 });
    }
  }
  
  augmentedCognitiveProgression.sort((a, b) => ALL_COGNITIVE_STAGES.indexOf(a.Stage) - ALL_COGNITIVE_STAGES.indexOf(b.Stage));

  const activeActionsFormatted = activeActions.map(d => ({
    Stage: d.stage_name,
    Scaffold: d.scaffold_name.replace(' Scaffold', ''),
    Count: d.count
  }));

  const augmentedActiveActions = [...activeActionsFormatted];
  const firstScaffold = activeActionsFormatted.length > 0
    ? activeActionsFormatted[0].Scaffold
    : (activeTab === 'homework' ? HOMEWORK_SCAFFOLDS[0] : STUDY_SCAFFOLDS[0]).replace(' Scaffold', '');

  for (const stage of ALL_COGNITIVE_STAGES) {
    if (!augmentedActiveActions.some(d => d.Stage === stage)) {
      augmentedActiveActions.push({ Stage: stage, Scaffold: firstScaffold, Count: 0 });
    }
  }
  
  augmentedActiveActions.sort((a, b) => ALL_COGNITIVE_STAGES.indexOf(a.Stage) - ALL_COGNITIVE_STAGES.indexOf(b.Stage));

  const maxTime = time_utilization.length > 0
    ? Math.max(...time_utilization.map(t => t.chat + t.editor + t.terminal))
    : 0;
  const timeMultiplier = maxTime > 0 && maxTime < 1.0 ? 60 : 1;
  const timeUnit = maxTime > 0 && maxTime < 1.0 ? 'm' : 'h';

  const scaledTimeData = time_utilization.map(t => ({
    ...t,
    chat: Math.round(t.chat * timeMultiplier * 10) / 10,
    editor: Math.round(t.editor * timeMultiplier * 10) / 10,
    terminal: Math.round(t.terminal * timeMultiplier * 10) / 10,
  }));

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: 24, marginTop: 24 }}>

      {/* Cognitive Progression Heatmap */}
      <Card style={{ padding: 20, height: 350 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>Cognitive Progression</div>
        <ResponsiveContainer width="100%" height="90%">
          <ScatterChart margin={{ top: 20, right: 40, left: 20, bottom: 25 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={D.border} vertical={false} />
            <XAxis type="category" dataKey="Week" allowDuplicatedCategory={false} stroke={D.muted} fontSize={12} tickMargin={10} padding={{ left: 30, right: 30 }} tickFormatter={(val) => val.includes('Unknown') ? 'Unknown' : `Week ${val}`} />
            <YAxis
              type="category"
              dataKey="Stage"
              allowDuplicatedCategory={false}
              stroke={D.muted}
              fontSize={12}
              tickMargin={10}
              padding={{ top: 30, bottom: 30 }}
              width={110}
              interval={0}
              ticks={["Refactoring", "Debugging", "Implementing", "Conceptualizing"]}
            />
            <ZAxis dataKey="Count" range={[0, 100]} />
            <RechartsTooltip
              cursor={{ strokeDasharray: '3 3' }}
              contentStyle={{ borderRadius: 8, border: `1px solid ${D.border}`, boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
            />
            <Scatter data={augmentedCognitiveProgression} shape={(props: unknown) => renderHeatmapRect(props as Parameters<typeof renderHeatmapRect>[0], Math.max(1, ...augmentedCognitiveProgression.map((d) => d.Count)), D.blue)} />
          </ScatterChart>
        </ResponsiveContainer>
      </Card>

      {/* Time Utilization Stacked Bar */}
      <Card style={{ padding: 20, height: 350 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>Time Utilization Per Week</div>
        <ResponsiveContainer width="100%" height="90%">
          <BarChart data={scaledTimeData} margin={{ top: 20, right: 30, left: 20, bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={D.border} vertical={false} />
            <XAxis dataKey="assignment" stroke={D.muted} fontSize={12} tickMargin={10} />
            <YAxis stroke={D.muted} fontSize={12} tickFormatter={(val) => `${val}${timeUnit}`} />
            <RechartsTooltip
              cursor={{ fill: D.surface }}
              contentStyle={{ background: D.card, borderColor: D.border, color: D.text }}
              formatter={(value: any, name: any) => [`${value}${timeUnit}`, name]}
            />
            <Legend wrapperStyle={{ fontSize: 12, color: D.muted }} />
            <Bar dataKey="chat" name="Chat" stackId="a" fill="#3b82f6" />
            <Bar dataKey="editor" name="Editor" stackId="a" fill="#8b5cf6" />
            <Bar dataKey="terminal" name="Terminal" stackId="a" fill="#ec4899" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Card>

      {/* Pedagogical Actions Heatmap */}
      <Card style={{ padding: 20, height: 400 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>Pedagogical Actions</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => setActiveTab('homework')}
              style={{
                background: activeTab === 'homework' ? D.surface : 'transparent',
                border: `1px solid ${activeTab === 'homework' ? D.border : 'transparent'}`,
                color: D.text, padding: '4px 8px', borderRadius: 6, fontSize: 12, cursor: 'pointer'
              }}
            >
              Homework
            </button>
            <button
              onClick={() => setActiveTab('study')}
              style={{
                background: activeTab === 'study' ? D.surface : 'transparent',
                border: `1px solid ${activeTab === 'study' ? D.border : 'transparent'}`,
                color: D.text, padding: '4px 8px', borderRadius: 6, fontSize: 12, cursor: 'pointer'
              }}
            >
              Study Assist
            </button>
          </div>
        </div>

        <div style={{ fontSize: 12, color: D.muted, marginBottom: 8, textAlign: 'center' }}>
          {activeTab === 'homework' ? 'Showing Scaffolds for Homework Mode' : 'Showing Scaffolds for Study Assist Mode'}
        </div>

        {augmentedActiveActions.some(d => d.Count > 0) ? (
          <ResponsiveContainer width="100%" height="80%">
            <ScatterChart margin={{ top: 20, right: 40, bottom: 40, left: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={D.border} />
              <XAxis
                type="category"
                dataKey="Stage"
                allowDuplicatedCategory={false}
                stroke={D.muted}
                fontSize={10}
                tickMargin={8}
                padding={{ left: 20, right: 20 }}
                interval={0}
                ticks={ALL_COGNITIVE_STAGES}
              />
              <YAxis type="category" dataKey="Scaffold" allowDuplicatedCategory={false} stroke={D.muted} fontSize={11} width={110} padding={{ top: 30, bottom: 30 }} interval={0} />
              <ZAxis dataKey="Count" range={[0, 100]} />
              <RechartsTooltip
                cursor={{ strokeDasharray: '3 3' }}
                contentStyle={{ borderRadius: 8, border: `1px solid ${D.border}`, boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
              />
              <Scatter
                data={augmentedActiveActions}
                shape={(props: unknown) => renderHeatmapRect(props as Parameters<typeof renderHeatmapRect>[0], Math.max(1, ...augmentedActiveActions.map(d => d.Count)), activeTab === 'study' ? D.orange : D.purple)}
              />
            </ScatterChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '80%', color: D.muted, fontSize: 14 }}>
            {activeTab === 'homework' ? 'No Homework Assist data available.' : 'No Study Assist data available.'}
          </div>
        )}
      </Card>

      {/* Frustration by Week */}
      <Card style={{ padding: 20, height: 400 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>Frustration by Week</div>
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={D.border} />
            <XAxis type="category" dataKey="week" name="Week" stroke={D.muted} fontSize={12} />
            <YAxis type="number" dataKey="frustration" name="Frustration Level" domain={[0, 'dataMax + 1']} stroke={D.muted} fontSize={12} label={{ value: 'Frustration →', angle: -90, position: 'insideLeft', fill: D.muted, fontSize: 12 }} />
            <ZAxis type="number" dataKey="queries" range={[100, 1000]} name="Volume" />
            <RechartsTooltip
              cursor={{ strokeDasharray: '3 3' }}
              contentStyle={{ background: D.card, borderColor: D.border, color: D.text }}
              formatter={(value: unknown, name: unknown, props: { payload?: { week?: string } }) => {
                if (name === 'Volume') return [`${String(value)} queries`, props.payload?.week || 'Week'];
                return [String(value), String(name)];
              }}
            />
            <Scatter name="Frustration" data={frustration_by_week} fill="#ef4444" opacity={0.7} />
          </ScatterChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );
}
