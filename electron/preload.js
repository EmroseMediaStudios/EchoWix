const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('wickmind', {
  platform: process.platform,
  version: require('./package.json').version,
});
