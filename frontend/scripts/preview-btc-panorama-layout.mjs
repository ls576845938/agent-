import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {arrangeBtcPanorama, inspectBtcPanoramaRoutes} from '../src/workspaces/architecture/btcPanoramaLayout.ts';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.resolve(here, '../src/workspaces/architecture/btcPanoramaData.ts'), 'utf8');
const block = source.split('// BTC_PANORAMA_DATA_START')[1].split('// BTC_PANORAMA_DATA_END')[0];
const panorama = JSON.parse(block.split('export const btcSystemPanorama: BtcSystemPanorama =')[1].trim().replace(/;$/, ''));
const initialNodes = panorama.groups.flatMap(group => [
  {id: `group-${group.id}`, position: {x: group.x, y: group.y}, style: {width: group.width, height: group.height}, data: {kind: 'group'}},
  ...group.nodes.map(node => ({id: node.id, parentId: `group-${group.id}`, position: {x: node.x - group.x, y: node.y - group.y}, style: {width: node.width, height: node.height}, data: {kind: 'node'}})),
]);
const initialEdges = panorama.edges.map(edge => ({id: edge.id, source: edge.from, target: edge.to, label: edge.label ?? ''}));
const {nodes, routes} = await arrangeBtcPanorama(initialNodes, initialEdges);
const collisions = inspectBtcPanoramaRoutes(nodes, initialEdges, routes);
if (collisions.length) throw new Error(`route collision contract failed: ${collisions.join(', ')}`);

const groups = panorama.groups.map(group => {
  const frame = nodes.find(node => node.id === `group-${group.id}`);
  return {
    ...group,
    x: frame.position.x,
    y: frame.position.y,
    width: Number(frame.style.width),
    height: Number(frame.style.height),
    nodes: group.nodes.map(original => {
      const node = nodes.find(item => item.id === original.id);
      return {...original, x: frame.position.x + node.position.x, y: frame.position.y + node.position.y};
    }),
  };
});
const canvas = {
  width: Math.ceil(Math.max(...groups.map(group => group.x + group.width)) + 170),
  height: Math.ceil(Math.max(...groups.map(group => group.y + group.height)) + 120),
};
const esc = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const wrap = (value, max = 22) => String(value).split('\n').flatMap(explicit => {
  const lines = [];
  for (let index = 0; index < explicit.length; index += max) lines.push(explicit.slice(index, index + max));
  return lines.length ? lines : [''];
});
const polyline = points => points.map(point => `${point.x},${point.y}`).join(' ');

const groupSvg = groups.map(group => `<g><rect class="group" x="${group.x}" y="${group.y}" width="${group.width}" height="${group.height}" rx="24"/><text class="group-title" x="${group.x + 24}" y="${group.y + 39}">${esc(group.title)}</text></g>`).join('\n');
const edgeSvg = panorama.edges.map(edge => `<polyline class="edge ${edge.style === 'dashed' ? 'dashed' : ''}" points="${polyline(routes.get(edge.id).points)}" marker-end="url(#arrow)"${edge.both ? ' marker-start="url(#arrow-start)"' : ''}/>`).join('\n');
const nodeSvg = groups.flatMap(group => group.nodes.map(node => {
  const title = wrap(node.title, 20).slice(0, 2);
  const detail = wrap(node.detail, 24).slice(0, 4);
  return `<g><rect class="node" x="${node.x}" y="${node.y}" width="${node.width}" height="${node.height}" rx="17"/>
    <text class="node-title" x="${node.x + 18}" y="${node.y + 31}">${title.map((line, index) => `<tspan x="${node.x + 18}" dy="${index ? 22 : 0}">${esc(line)}</tspan>`).join('')}</text>
    <text class="node-detail" x="${node.x + 18}" y="${node.y + 75}">${detail.map((line, index) => `<tspan x="${node.x + 18}" dy="${index ? 17 : 0}">${esc(line)}</tspan>`).join('')}</text></g>`;
})).join('\n');
const labelSvg = panorama.edges.filter(edge => edge.label).map(edge => {
  const route = routes.get(edge.id);
  const width = Math.max(120, edge.label.length * 14 + 24);
  return `<g><rect class="label-bg" x="${route.labelX - width / 2}" y="${route.labelY - 17}" width="${width}" height="30" rx="10"/><text class="edge-label" x="${route.labelX}" y="${route.labelY + 4}">${esc(edge.label)}</text></g>`;
}).join('\n');

const svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${canvas.width}" height="${canvas.height}" viewBox="0 0 ${canvas.width} ${canvas.height}">
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#91a9c2"/></marker><marker id="arrow-start" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 10 0 L 0 5 L 10 10 z" fill="#91a9c2"/></marker></defs>
<style>.group{fill:#111c2a;stroke:#526b86;stroke-width:2}.group-title{fill:#d5e5f7;font:700 19px "Microsoft YaHei",sans-serif}.node{fill:#23384f;stroke:#7793af;stroke-width:2}.node-title{fill:#f0f6ff;font:700 17px "Microsoft YaHei",sans-serif}.node-detail{fill:#bed0e3;font:14px "Microsoft YaHei",sans-serif}.edge{fill:none;stroke:#91a9c2;stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round}.edge.dashed{stroke-dasharray:9 7}.label-bg{fill:#111c2a;stroke:#3a526d}.edge-label{fill:#dbeafe;text-anchor:middle;font:650 13px "Microsoft YaHei",sans-serif}</style>
<rect width="100%" height="100%" fill="#090f18"/>${groupSvg}${edgeSvg}${nodeSvg}${labelSvg}</svg>`;

const outputDir = path.resolve(here, '../output/playwright/btc-panorama-20260929/layout-preview');
fs.mkdirSync(outputDir, {recursive: true});
const svgPath = path.join(outputDir, 'btc-panorama-elk-two-level-preview.svg');
fs.writeFileSync(svgPath, svg);
console.log(JSON.stringify({svgPath, canvas, nodeCount: 37, edgeCount: routes.size, collisions}, null, 2));
