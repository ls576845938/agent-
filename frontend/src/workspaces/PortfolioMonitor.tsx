import {useLocation} from 'react-router-dom';
import LegacyPortfolioMonitor from './portfolio/LegacyPortfolioMonitor';
import ResearchPortfolioWorkspace from './ResearchPortfolioWorkspace';
export default function PortfolioMonitor() {
  const location = useLocation();
  if (new URLSearchParams(location.search).get('layout') === 'legacy') return <><a className="research-return-new" href="/portfolio">返回新版投资组合</a><LegacyPortfolioMonitor /></>;
  return <ResearchPortfolioWorkspace key={location.search} surface="portfolio" />;
}
