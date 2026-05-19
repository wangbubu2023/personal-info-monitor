import React from 'react';

/** 三页顶栏中文主标题 */
export const pageHeroTitleCnClass =
  'text-[19px] font-semibold leading-tight tracking-tight text-[#2c3a50] sm:text-[20px]';

/** 英文副标题：与主 UI 同一无衬线，斜体区分层级。 */
export const pageHeroSubtitleEnClass =
  'mt-1 max-w-2xl font-sans text-[17px] font-semibold italic leading-none tracking-[0.03em] text-[#6f7f94] sm:text-[19px]';

interface PageHeroTitleProps {
  titleZh: string;
  titleEn: string;
  'data-testid'?: string;
}

/**
 * 资讯中心 / 个人简报 / 系统设置 等页顶栏：中文标题 + 英文副标题，间距与样式统一。
 */
const PageHeroTitle: React.FC<PageHeroTitleProps> = ({
  titleZh,
  titleEn,
  'data-testid': testId,
}) => (
  <div className="min-w-0">
    <h1 className={pageHeroTitleCnClass} data-testid={testId}>
      {titleZh}
    </h1>
    <p className={pageHeroSubtitleEnClass} lang="en">
      {titleEn}
    </p>
  </div>
);

export default PageHeroTitle;
