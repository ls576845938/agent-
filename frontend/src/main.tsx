import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';

import App from './App';
import './index.css';
import './workbench.css';
import './terminal-workbench.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
