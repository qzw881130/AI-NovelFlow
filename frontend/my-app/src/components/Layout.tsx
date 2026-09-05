import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import CoffeeButton from './CoffeeButton';
import { SidebarProvider, useSidebar } from '../contexts/SidebarContext';

function LayoutContent() {
  const { sidebarWidth } = useSidebar();

  return (
    <>
      <Sidebar />
      <main
        id="main-content"
        tabIndex={-1}
        className="min-h-screen min-w-0 transition-[margin,width] duration-300 motion-reduce:transition-none"
        style={{
          marginLeft: `${sidebarWidth}px`,
          width: `calc(100% - ${sidebarWidth}px)`
        }}
      >
        <div className="w-full px-4 pt-6 pb-24 sm:px-6 lg:px-8 lg:pb-6">
          <Outlet />
        </div>
      </main>
      <CoffeeButton />
    </>
  );
}

export default function Layout() {
  return (
    <SidebarProvider>
      <div className="min-h-screen bg-gray-50">
        <LayoutContent />
      </div>
    </SidebarProvider>
  );
}
