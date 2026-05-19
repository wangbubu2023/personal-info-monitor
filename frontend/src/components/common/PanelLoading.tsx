import React from 'react';
import { motion } from 'framer-motion';
import { Activity } from 'lucide-react';

interface PanelLoadingProps {
  /** 面板内占位高度，避免布局跳动 */
  className?: string;
  message?: string;
}

/**
 * 用于卡片、Tab 内容区等局部加载，视觉与 PageLoading 一致但更紧凑。
 */
const PanelLoading: React.FC<PanelLoadingProps> = ({
  className = '',
  message = '正在准备内容…',
}) => (
  <div
    className={`flex min-h-[200px] flex-col items-center justify-center gap-5 px-6 py-10 sm:min-h-[240px] ${className}`}
    data-testid="panel-loading"
  >
    <div className="relative flex h-14 w-14 items-center justify-center sm:h-16 sm:w-16">
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ repeat: Infinity, duration: 2, ease: 'linear' }}
        className="absolute inset-0 rounded-2xl border-2 border-[#49A8C9]/25 border-t-[#49A8C9]"
      />
      <motion.div
        animate={{ rotate: -360 }}
        transition={{ repeat: Infinity, duration: 3, ease: 'linear' }}
        className="absolute inset-1.5 rounded-xl border border-[#8C866A]/20 border-b-[#8C866A]"
      />
      <Activity className="h-6 w-6 text-[#49A8C9] sm:h-7 sm:w-7" strokeWidth={1.5} />
    </div>
    <div className="flex flex-col items-center gap-1 text-center">
      <span className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[#586476]">加载中</span>
      <span className="text-[13px] font-medium text-[#5f6f82]">{message}</span>
    </div>
  </div>
);

export default PanelLoading;
