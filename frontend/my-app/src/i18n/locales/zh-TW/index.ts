// zh-TW 模块整合文件
import common from './common';
import nav from './nav';
import welcome from './welcome';
import novels from './novels';
import characters from './characters';
import scenes from './scenes';
import props from './props';
import tasks from './tasks';
import settings from './settings';
import logs from './logs';
import chapters from './chapters';
import misc from './misc';

export default {
  ...common,
  ...nav,
  ...welcome,
  ...novels,
  ...characters,
  ...scenes,
  ...props,
  ...tasks,
  ...settings,
  ...logs,
  ...chapters,
  ...misc,
};
