import { Link, useLocation } from 'react-router-dom';
import {
  Home,
  Settings,
  BookOpen,
  ListTodo,
  Users,
  MapPin,
  Package,
  Sparkles,
  FlaskConical,
  FileText,
  ScrollText,
  Globe,
  ChevronLeft,
  ChevronRight
} from 'lucide-react';
import clsx from 'clsx';
import { useTranslation } from '../stores/i18nStore';
import { useSidebar } from '../contexts/SidebarContext';

export default function Sidebar() {
  const location = useLocation();
  const { t } = useTranslation();
  const { isCollapsed, toggleSidebar } = useSidebar();

  const navigation = [
    { name: t('nav.welcome'), href: '/welcome', icon: Home },
    { name: t('nav.novels'), href: '/novels', icon: BookOpen },
    { name: t('nav.characters'), href: '/characters', icon: Users },
    { name: t('nav.scenes'), href: '/scenes', icon: MapPin },
    { name: t('nav.props'), href: '/props', icon: Package },
    { name: t('nav.tasks'), href: '/tasks', icon: ListTodo },
    { name: t('nav.testCases'), href: '/test-cases', icon: FlaskConical },
    { name: t('nav.systemSettings'), href: '/settings', icon: Settings },
    { name: t('nav.promptConfig'), href: '/prompt-config', icon: FileText },
    { name: t('nav.uiConfig'), href: '/ui-config', icon: Globe },
    { name: t('nav.llmLogs'), href: '/llm-logs', icon: ScrollText },
  ];

  return (
    <div
      className={clsx(
        "hidden lg:fixed lg:inset-y-0 lg:z-50 lg:flex lg:flex-col transition-all duration-300 ease-in-out",
        isCollapsed ? "lg:w-20" : "lg:w-64"
      )}
    >
      <div className="flex grow flex-col gap-y-5 overflow-y-auto bg-white border-r border-gray-200 pb-4 relative">
        <div className={clsx(
          "flex h-16 shrink-0 items-center transition-all duration-300 relative",
          isCollapsed ? "justify-center px-2" : "px-6 gap-2"
        )}>
          <Sparkles className="h-8 w-8 text-primary-600 shrink-0" />
          {!isCollapsed && (
            <span className="text-xl font-bold text-gray-900 whitespace-nowrap">NovelFlow</span>
          )}
        </div>
        <button
          onClick={toggleSidebar}
          className={clsx(
            "absolute top-8 -right-3 w-6 h-6 rounded-full bg-white border border-gray-300 shadow-sm flex items-center justify-center hover:bg-gray-50 transition-colors z-10 hover:border-gray-400",
            isCollapsed && "rotate-180"
          )}
          title={isCollapsed ? t('common.expand') : t('common.collapse')}
        >
          {isCollapsed ? (
            <ChevronRight className="h-4 w-4 text-gray-600" />
          ) : (
            <ChevronLeft className="h-4 w-4 text-gray-600" />
          )}
        </button>
        <nav className="flex flex-1 flex-col">
          <ul role="list" className="flex flex-1 flex-col gap-y-7">
            <li>
              <ul role="list" className={clsx(
                "space-y-1 transition-all duration-300",
                isCollapsed ? "px-2" : "-mx-2 px-2"
              )}>
                {navigation.map((item) => (
                  <li key={item.name}>
                    <Link
                      to={item.href}
                      className={clsx(
                        location.pathname === item.href
                          ? 'bg-primary-50 text-primary-600'
                          : 'text-gray-700 hover:text-primary-600 hover:bg-gray-50',
                        'group flex gap-x-3 rounded-md p-2 text-sm leading-6 font-semibold transition-colors',
                        isCollapsed ? 'justify-center' : ''
                      )}
                      title={isCollapsed ? item.name : undefined}
                    >
                      <item.icon
                        className={clsx(
                          location.pathname === item.href
                            ? 'text-primary-600'
                            : 'text-gray-400 group-hover:text-primary-600',
                          'h-6 w-6 shrink-0 transition-colors'
                        )}
                        aria-hidden="true"
                      />
                      {!isCollapsed && item.name}
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
