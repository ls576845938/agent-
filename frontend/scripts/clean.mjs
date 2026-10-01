import {rmSync} from 'node:fs';
import {resolve} from 'node:path';

const target = resolve(process.cwd(), 'dist');
rmSync(target, {recursive: true, force: true});
