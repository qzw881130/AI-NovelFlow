import { useEffect, useRef, useState } from 'react';
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
  ChevronRight,
  Menu,
  X
} from 'lucide-react';
import clsx from 'clsx';
import { useTranslation } from '../stores/i18nStore';
import { useSidebar } from '../contexts/SidebarContext';

export default function Sidebar() {
  const location = useLocation();
  const { t } = useTranslation();
  const { isCollapsed, toggleSidebar, isDesktop } = useSidebar();
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setIsMobileOpen(false);
  }, [location, isDesktop]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || !isMobileOpen || isDesktop) return;

    dialog.showModal();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      if (menuButtonRef.current?.getClientRects().length) menuButtonRef.current.focus();
    };
  }, [isMobileOpen, isDesktop]);

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

  const navigationLinks = (collapsed: boolean) => (
    <nav aria-label="NovelFlow" className="flex flex-1 flex-col">
      <ul className={clsx('space-y-1 px-2', !collapsed && 'lg:-mx-2')}>
        {navigation.map((item) => {
          const isActive = location.pathname === item.href || location.pathname.startsWith(`${item.href}/`);
          return (
            <li key={item.href}>
              <Link
                to={item.href}
                onClick={() => setIsMobileOpen(false)}
                aria-label={item.name}
                aria-current={isActive ? 'page' : undefined}
                title={collapsed ? item.name : undefined}
                className={clsx(
                  isActive ? 'bg-primary-50 text-primary-600' : 'text-gray-700 hover:text-primary-600 hover:bg-gray-50',
                  'group flex min-h-[44px] items-center gap-x-3 rounded-md p-2 text-sm leading-6 font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary-600 lg:min-h-0',
                  collapsed && 'justify-center'
                )}
              >
                <item.icon aria-hidden="true" className={clsx('h-6 w-6 shrink-0 transition-colors', isActive ? 'text-primary-600' : 'text-gray-400 group-hover:text-primary-600')} />
                {!collapsed && item.name}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );

  return (
    <>
      <header className="flex h-16 items-center gap-3 border-b border-gray-200 bg-white px-4 lg:hidden">
        <button
          ref={menuButtonRef}
          type="button"
          onClick={() => setIsMobileOpen(true)}
          aria-label={`${t('common.expand')} NovelFlow`}
          aria-expanded={isMobileOpen}
          aria-controls="mobile-navigation"
          aria-haspopup="dialog"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-gray-700 hover:bg-gray-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary-600"
        >
          <Menu aria-hidden="true" className="h-6 w-6" />
        </button>
        <Link to="/welcome" className="flex items-center gap-2 text-xl font-bold text-gray-900">
          <Sparkles aria-hidden="true" className="h-7 w-7 text-primary-600" />
          NovelFlow
        </Link>
      </header>
      <dialog
        ref={dialogRef}
        id="mobile-navigation"
        aria-labelledby="mobile-navigation-title"
        onClose={() => setIsMobileOpen(false)}
        onClick={(event) => {
          if (event.target === event.currentTarget) setIsMobileOpen(false);
        }}
        className="fixed inset-y-0 left-0 m-0 h-[100dvh] max-h-none w-80 max-w-[calc(100%_-_2rem)] border-0 bg-white p-0 shadow-xl backdrop:bg-gray-900/50"
      >
        <div className="flex min-h-full flex-col gap-5 pb-6">
          <div className="flex h-16 shrink-0 items-center justify-between gap-2 px-4">
            <span id="mobile-navigation-title" className="text-xl font-bold text-gray-900">NovelFlow</span>
            <button type="button" autoFocus onClick={() => setIsMobileOpen(false)} aria-label={t('common.close')}
              className="flex h-11 w-11 items-center justify-center rounded-md text-gray-700 hover:bg-gray-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary-600">
              <X aria-hidden="true" className="h-6 w-6" />
            </button>
          </div>
          {navigationLinks(false)}
        </div>
      </dialog>
      <div
        className={clsx(
          'hidden lg:fixed lg:inset-y-0 lg:z-50 lg:flex lg:flex-col transition-all duration-300 ease-in-out motion-reduce:transition-none',
          isCollapsed ? 'lg:w-20' : 'lg:w-64'
        )}
      >
        <div className="flex grow flex-col gap-y-5 overflow-y-auto bg-white border-r border-gray-200 pb-4 relative">
          <div className={clsx(
            'flex h-16 shrink-0 items-center transition-all duration-300 relative',
            isCollapsed ? 'justify-center px-2' : 'px-6 gap-2'
          )}>
            <Sparkles aria-hidden="true" className="h-8 w-8 text-primary-600 shrink-0" />
            {!isCollapsed && (
              <span className="text-xl font-bold text-gray-900 whitespace-nowrap">NovelFlow</span>
            )}
          </div>
          <button
            onClick={toggleSidebar}
            type="button"
            aria-label={isCollapsed ? t('common.expand') : t('common.collapse')}
            aria-expanded={!isCollapsed}
            className="absolute top-8 right-0 w-6 h-6 rounded-full bg-white border border-gray-300 shadow-sm flex items-center justify-center hover:bg-gray-50 transition-colors z-10 hover:border-gray-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary-600"
            title={isCollapsed ? t('common.expand') : t('common.collapse')}
          >
            {isCollapsed ? (
              <ChevronRight aria-hidden="true" className="h-4 w-4 text-gray-600" />
            ) : (
              <ChevronLeft aria-hidden="true" className="h-4 w-4 text-gray-600" />
            )}
          </button>
          {navigationLinks(isCollapsed)}
        </div>
      </div>
    </>
  );
}
