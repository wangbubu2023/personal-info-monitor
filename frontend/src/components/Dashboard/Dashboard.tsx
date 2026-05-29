import React, { Suspense } from 'react';
import { useDashboard } from '../../hooks/useDashboard';
import DashboardHeader from './DashboardHeader';
import DashboardQueueStatus from './DashboardQueueStatus';
import DashboardCategoryTabs from './DashboardCategoryTabs';
import DashboardDigestList from './DashboardDigestList';
import { DASHBOARD_CATEGORIES } from './dashboardTypes'
import { getDashboardCategoryCount } from './dashboardUtils'
import { PageLoading } from '../common'

const DashboardSearchResults = React.lazy(() => import('./DashboardSearchResults'))

const Dashboard: React.FC = () => {
  const {
    searchQuery,
    selectedSourceId,
    selectedSourceName,
    selectedDate,
    setSelectedDate,
    activeTab,
    setActiveTab,
    stats,
    statsLoading,
    digest,
    digestLoading,
    queueStatus,
    queueLoading,
    currentItems,
    contentItems,
    contentTotal,
    contentLoading,
    fetchAll,
    isFetchingAll,
    clearContentFilter,
  } = useDashboard();

  if (statsLoading && !searchQuery && !selectedSourceId) {
    return <PageLoading />;
  }

  if (searchQuery || selectedSourceId) {
    return (
      <Suspense fallback={<PageLoading />}>
        <DashboardSearchResults
          searchQuery={searchQuery}
          sourceName={selectedSourceName}
          sourceId={selectedSourceId}
          total={contentTotal}
          items={contentItems}
          isLoading={contentLoading}
          onClear={clearContentFilter}
        />
      </Suspense>
    );
  }

  return (
    <div className="min-h-screen bg-[#f5f9fc] pb-16 pt-1" data-testid="dashboard-page">
      <div className="mx-auto max-w-feed pl-5 pr-6 sm:pl-7 sm:pr-8 lg:pl-9 lg:pr-10">
        <div className="border-b border-[rgba(88,100,118,0.1)] pb-3">
          <DashboardHeader
            stats={stats}
            selectedDate={selectedDate}
            onDateChange={setSelectedDate}
            onFetchAll={fetchAll}
            isFetching={isFetchingAll}
          />
        </div>
      </div>

      <div className="mx-auto mt-5 max-w-feed pl-5 pr-6 sm:pl-7 sm:pr-8 lg:pl-9 lg:pr-10">
        <div className="rounded-2xl border border-[rgba(88,100,118,0.12)] bg-white/95 p-1 shadow-[0_12px_40px_-18px_rgba(41,56,89,0.14)] backdrop-blur-sm">
          <div className="flex flex-col gap-2.5 border-b border-[rgba(88,100,118,0.08)] px-3 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-5 sm:px-4 sm:py-3">
            <DashboardCategoryTabs
              borderless
              categories={DASHBOARD_CATEGORIES}
              activeTab={activeTab}
              getCategoryCount={(key) => getDashboardCategoryCount(digest, key)}
              onSelect={setActiveTab}
            />
            <DashboardQueueStatus variant="inline" queueStatus={queueStatus} isLoading={queueLoading} />
          </div>
          <div className="px-3 pb-4 pt-3 sm:px-4 sm:pb-5 sm:pt-4">
            <DashboardDigestList
              isLoading={digestLoading}
              items={currentItems}
              selectedDate={selectedDate}
              activeTab={activeTab}
              categories={DASHBOARD_CATEGORIES}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
