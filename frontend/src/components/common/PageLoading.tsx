import React from 'react';
import { motion } from 'framer-motion';
import { Activity } from 'lucide-react';

const PageLoading: React.FC = () => (
  <div className="flex h-[70vh] flex-col items-center justify-center gap-7">
    <div className="relative flex h-20 w-20 items-center justify-center">
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ repeat: Infinity, duration: 2, ease: 'linear' }}
        className="absolute inset-0 rounded-2xl border-2 border-[#49A8C9]/25 border-t-[#49A8C9]"
      />
      <motion.div
        animate={{ rotate: -360 }}
        transition={{ repeat: Infinity, duration: 3, ease: 'linear' }}
        className="absolute inset-2 rounded-xl border border-[#8C866A]/20 border-b-[#8C866A]"
      />
      <Activity className="h-8 w-8 text-[#49A8C9]" />
    </div>
    <div className="flex flex-col items-center gap-1.5 text-center">
      <h3 className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[#586476]">加载中</h3>
      <p className="text-[13px] font-medium text-[#586476]/90">正在准备内容…</p>
    </div>
  </div>
);

export default PageLoading;
