import { Link, useLocation } from 'react-router-dom';
import { 
  Home, 
  Settings, 
  BookOpen, 
  ListTodo, 
  Users,
  MapPin,
  Sparkles,
  FlaskConical,
  FileText,
  ScrollText,
  Globe
} from 'lucide-react';
import clsx from 'clsx';
import { useTranslation } from '../stores/i18nStore';

export default function Sidebar() {
  const location = useLocation();
  const { t } = useTranslation();

  const navigation = [
    { name: t('nav.welcome'), href: '/welcome', icon: Home },
    { name: t('nav.novels'), href: '/novels', icon: BookOpen },
    { name: t('nav.characters'), href: '/characters', icon: Users },
    { name: t('nav.scenes'), href: '/scenes', icon: MapPin },
    { name: t('nav.tasks'), href: '/tasks', icon: ListTodo },
    { name: t('nav.testCases'), href: '/test-cases', icon: FlaskConical },
    { name: t('nav.systemSettings'), href: '/settings', icon: Settings },
    { name: t('nav.promptConfig'), href: '/prompt-config', icon: FileText, highlight: true },
    { name: t('nav.uiConfig'), href: '/ui-config', icon: Globe },
    { name: t('nav.llmLogs'), href: '/llm-logs', icon: ScrollText },
  ];

  return (
    <div className="hidden lg:fixed lg:inset-y-0 lg:z-50 lg:flex lg:w-64 lg:flex-col">
      <div className="flex grow flex-col gap-y-5 overflow-y-auto bg-white border-r border-gray-200 px-6 pb-4">
        <div className="flex h-16 shrink-0 items-center gap-2">
          <Sparkles className="h-8 w-8 text-primary-600" />
          <span className="text-xl font-bold text-gray-900">NovelFlow</span>
        </div>
        <nav className="flex flex-1 flex-col">
          <ul role="list" className="flex flex-1 flex-col gap-y-7">
            <li>
              <ul role="list" className="-mx-2 space-y-1">
                {navigation.map((item) => (
                  <li key={item.name}>
                    <Link
                      to={item.href}
                      className={clsx(
                        location.pathname === item.href
                          ? item.highlight
                            ? 'bg-red-50 text-red-600'
                            : 'bg-primary-50 text-primary-600'
                          : item.highlight
                            ? 'text-red-500 hover:text-red-600 hover:bg-red-50'
                            : 'text-gray-700 hover:text-primary-600 hover:bg-gray-50',
                        'group flex gap-x-3 rounded-md p-2 text-sm leading-6 font-semibold transition-colors'
                      )}
                    >
                      <item.icon
                        className={clsx(
                          location.pathname === item.href
                            ? item.highlight
                              ? 'text-red-600'
                              : 'text-primary-600'
                            : item.highlight
                              ? 'text-red-400 group-hover:text-red-600'
                              : 'text-gray-400 group-hover:text-primary-600',
                          'h-6 w-6 shrink-0 transition-colors'
                        )}
                        aria-hidden="true"
                      />
                      {item.name}
                    </Link>
                  </li>
                ))}
              </ul>
            </li>
          </ul>
        </nav>
      </div>
    </div>
  );
}
