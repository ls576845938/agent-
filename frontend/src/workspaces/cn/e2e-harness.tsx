import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';

import CNEquityWorkspace from '../CNEquityWorkspace';
import '../../index.css';

const root = document.getElementById('root');
if (!root) throw new Error('cn_equity_e2e_root_missing');

createRoot(root).render(
  <StrictMode>
    <CNEquityWorkspace />
  </StrictMode>,
);
