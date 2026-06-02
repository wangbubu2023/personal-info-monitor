import React, { Suspense, lazy, useMemo, useCallback, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Cpu, Database, Tag as TagIcon, MessageSquareText, ShieldAlert, ShieldCheck, Gauge, Activity } from 'lucide-react';
import { motion } from 'framer-motion';
import { KEYWORD_MONITORING_ENABLED, SCORE_LAB_BUILD_ENABLED } from '../../config/features';
import PanelLoading from '../common/PanelLoading';
import PageHeroTitle from '../common/PageHeroTitle';

const SourceManager = lazy(() => import('../SourceList/SourceManager'));
const FetchHealthTab = lazy(() => import('./FetchHealthTab'));
const CredentialsTab = lazy(() => import('./CredentialsTab'));
const AIModelTab = lazy(() => import('./AIModelTab'));
const TaskPromptsTab = lazy(() => import('./TaskPromptsTab'));

/**
 * URL keys we used to ship: `api-keys` (API key tab) and `browser-sessions`
 * (persistent browser sessions tab). Both have been folded into the new
 * unified `credentials` tab. Keep bookmarks / old deep links working by
 * rewriting the query param on mount.
 */
const LEGACY_TAB_REDIRECTS: Record<string, string> = {
  'api-keys': 'credentials',
  'browser-sessions': 'credentials',
};

const iconStroke = 1.5

interface SettingsTabItem {
  key: string;
  label: string;
  icon: React.ElementType;
  description: string;
  content: React.ReactNode;
}

const Settings: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();

  const validTabKeys = useMemo(() => {
    const keys: string[] = ['sources', 'fetch-health', 'credentials', 'ai-model', 'task-prompts'];
    if (KEYWORD_MONITORING_ENABLED) keys.push('keywords');
    if (SCORE_LAB_BUILD_ENABLED) keys.push('score-lab');
    return keys;
  }, []);

  // Redirect bookmarks at ?tab=api-keys / ?tab=browser-sessions to the new
  // unified credentials tab. Done in a useEffect so it plays well with
  // React Router's search-params setter.
  useEffect(() => {
    const current = searchParams.get('tab');
    if (current && LEGACY_TAB_REDIRECTS[current]) {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('tab', LEGACY_TAB_REDIRECTS[current]);
          return next;
        },
        { replace: true },
      );
    }
  }, [searchParams, setSearchParams]);

  const tabItems: SettingsTabItem[] = [
    {
      key: 'sources',
      label: '监测源',
      icon: Database,
      description: '管理 RSS、网站与 X 等订阅。',
      content: <SourceManager />,
    },
    {
      key: 'fetch-health',
      label: '抓取健康',
      icon: Activity,
      description: '查看各信源的抓取成功率、失败诊断、冷却状态与 7 天画像。',
      content: <FetchHealthTab />,
    },
    {
      key: 'credentials',
      label: '登录与凭据',
      icon: ShieldAlert,
      description: '管理站点登录会话、YouTube / X 平台 API Key，以及旧版手动 Cookie。',
      content: <CredentialsTab />,
    },
    {
      key: 'ai-model',
      label: '智能引擎',
      icon: Cpu,
      description: '配置大模型接口与参数。',
      content: <AIModelTab />,
    },
    {
      key: 'task-prompts',
      label: '任务提示',
      icon: MessageSquareText,
      description: '后台任务使用的选稿说明与综述提示；当前含每小时简报。',
      content: <TaskPromptsTab />,
    },
  ];

  if (KEYWORD_MONITORING_ENABLED) {
    const KeywordsTab = lazy(() => import('./KeywordsTab'));
    tabItems.push({
      key: 'keywords',
      label: '关键词',
      icon: TagIcon,
      description: '为特定主题设置提醒与过滤。',
      content: <KeywordsTab />,
    });
  }

  if (SCORE_LAB_BUILD_ENABLED) {
    const ScoreLabSettingsTab = lazy(() => import('./ScoreLabSettingsTab'));
    tabItems.push({
      key: 'score-lab',
      label: '评分实验室',
      icon: Gauge,
      description: '开发模式下开启打分调试入口。',
      content: <ScoreLabSettingsTab />,
    });
  }

  /** 与 URL `?tab=` 同步，刷新后保留设置子 tab */
  const activeTab = useMemo(() => {
    const t = searchParams.get('tab');
    if (t && validTabKeys.includes(t)) return t;
    return 'sources';
  }, [searchParams, validTabKeys]);

  const setActiveTab = useCallback(
    (key: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (key === 'sources') next.delete('tab');
          else next.set('tab', key);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const activeItem = tabItems.find((item) => item.key === activeTab) || tabItems[0];

  return (
    <div className="min-h-screen bg-[#f5f9fc] pb-16" data-testid="settings-page">
      <div className="mx-auto max-w-page pl-5 pr-6 sm:pl-7 sm:pr-8 lg:pl-9 lg:pr-10">
        {/* 第一层：标题行 + 角标 */}
        <div className="flex flex-col gap-3.5 pb-1 pt-4 sm:gap-4 sm:pt-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <PageHeroTitle
              titleZh="系统设置"
              titleEn="System Settings"
              data-testid="settings-header-title"
            />
            <div className="flex shrink-0 items-center gap-1.5 self-start rounded-lg border border-[#8C866A]/18 bg-white/90 px-2.5 py-1.5 text-[12px] font-medium text-[#5e5a47] shadow-sm">
              <ShieldCheck size={13} strokeWidth={iconStroke} className="shrink-0 text-[#8C866A]" />
              本地优先
            </div>
          </div>
        </div>

        {/* 第二层：Tab + 当前页说明 */}
        <div
          className="mt-1 flex flex-col gap-2.5 border-b border-[rgba(88,100,118,0.1)] pb-3 pt-1 sm:flex-row sm:items-start sm:justify-between sm:gap-5"
          data-testid="settings-tabs"
        >
          <div className="min-w-0 flex-1" data-testid="settings-tab-list">
            <div className="-mx-0.5 flex flex-wrap gap-1 px-0.5">
              {tabItems.map((item) => {
                const isActive = activeTab === item.key;
                const Icon = item.icon;
                return (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => setActiveTab(item.key)}
                    data-testid={`settings-tab-${item.key}`}
                    className={`group relative flex items-center gap-1.5 rounded-full py-2 pl-3.5 pr-2.5 text-[12px] font-medium transition-colors sm:text-[13px] ${
                      isActive ? 'text-[#2c3a50]' : 'text-[#5f6f82] hover:text-[#2c3a50]'
                    }`}
                  >
                    <Icon
                      size={15}
                      strokeWidth={iconStroke}
                      className={`relative z-10 shrink-0 ${isActive ? 'text-[#49A8C9]' : 'text-[#8a96a5] group-hover:text-[#5f6f82]'}`}
                    />
                    <span className="relative z-10 whitespace-nowrap">{item.label}</span>
                    {isActive && (
                      <motion.div
                        layoutId="settings-pill"
                        className="absolute inset-0 z-0 rounded-full border border-[rgba(88,100,118,0.08)] bg-white shadow-sm"
                        transition={{ type: 'spring', bounce: 0.2, duration: 0.55 }}
                      />
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          <p
            className="max-w-full shrink-0 text-[12px] leading-relaxed text-[#6b7c8f] sm:max-w-[15rem] sm:pt-1 sm:text-right md:max-w-[19rem] lg:max-w-[23rem]"
            data-testid="settings-tab-description"
          >
            {activeItem.description}
          </p>
        </div>
      </div>

      <div className="mx-auto mt-5 max-w-page pl-5 pr-6 sm:pl-7 sm:pr-8 lg:pl-9 lg:pr-10" data-testid="settings-content">
        <Suspense
          fallback={
            <div className="rounded-2xl border border-[rgba(88,100,118,0.1)] bg-white px-4 py-5 shadow-[0_8px_28px_-18px_rgba(41,56,89,0.18)]">
                <PanelLoading message="正在加载该设置页…" />
            </div>
          }
        >
          <div className="min-w-0">{activeItem.content}</div>
        </Suspense>
      </div>
    </div>
  );
};

export default Settings;
