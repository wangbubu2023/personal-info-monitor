import React from 'react'
import SourceListContainer from './SourceListContainer'

/**
 * SourceManager — 对外保持原接口不变。
 * 内部逻辑已拆分到 SourceListContainer + useSourceList / useSourceEditor / useSourceImport。
 */
const SourceManager: React.FC = () => <SourceListContainer />

export default SourceManager
