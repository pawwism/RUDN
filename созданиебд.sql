CREATE DATABASE Hotel_VelvetSeasons;
GO

USE Hotel_VelvetSeasons;
GO

-- Таблица пользователей системы
CREATE TABLE Users (
    UserID INT IDENTITY(1,1) PRIMARY KEY,
    Login NVARCHAR(50) NOT NULL UNIQUE,
    Password NVARCHAR(100) NOT NULL,
    FullName NVARCHAR(100) NOT NULL,
    RoleID INT NOT NULL,
    Status NVARCHAR(20) NOT NULL DEFAULT 'Активен',
    LastLogin DATETIME NULL,
    CreatedDate DATETIME NOT NULL DEFAULT GETDATE()
);

-- Таблица ролей
CREATE TABLE Roles (
    RoleID INT IDENTITY(1,1) PRIMARY KEY,
    RoleName NVARCHAR(50) NOT NULL UNIQUE,
    Description NVARCHAR(200) NULL
);

-- Таблица смен
CREATE TABLE Shifts (
    ShiftID INT IDENTITY(1,1) PRIMARY KEY,
    ShiftDate DATE NOT NULL,
    AdminID INT NOT NULL,
    ManagerID INT NOT NULL,
    RoomServiceID INT NOT NULL,
    CreatedBy INT NOT NULL,
    CreatedDate DATETIME NOT NULL DEFAULT GETDATE(),
    FOREIGN KEY (AdminID) REFERENCES Users(UserID),
    FOREIGN KEY (ManagerID) REFERENCES Users(UserID),
    FOREIGN KEY (RoomServiceID) REFERENCES Users(UserID),
    FOREIGN KEY (CreatedBy) REFERENCES Users(UserID)
);

-- Таблица типов номеров
CREATE TABLE RoomTypes (
    RoomTypeID INT IDENTITY(1,1) PRIMARY KEY,
    TypeName NVARCHAR(50) NOT NULL UNIQUE,
    Description NVARCHAR(200) NULL,
    BasePrice DECIMAL(10,2) NOT NULL,
    Capacity INT NOT NULL,
    ImagePath NVARCHAR(255) NULL
);

-- Таблица номеров
CREATE TABLE Rooms (
    RoomID INT IDENTITY(1,1) PRIMARY KEY,
    RoomNumber NVARCHAR(10) NOT NULL UNIQUE,
    RoomTypeID INT NOT NULL,
    Status NVARCHAR(20) NOT NULL DEFAULT 'Свободен',
    Notes NVARCHAR(500) NULL,
    FOREIGN KEY (RoomTypeID) REFERENCES RoomTypes(RoomTypeID)
);

-- Таблица бронирований
CREATE TABLE Bookings (
    BookingID INT IDENTITY(1,1) PRIMARY KEY,
    ClientName NVARCHAR(100) NOT NULL,
    ClientPhone NVARCHAR(20) NULL,
    ClientEmail NVARCHAR(100) NULL,
    RoomID INT NOT NULL,
    CheckInDate DATE NOT NULL,
    CheckOutDate DATE NOT NULL,
    Adults INT NOT NULL DEFAULT 1,
    Children INT NOT NULL DEFAULT 0,
    BookingType NVARCHAR(20) NOT NULL,
    Status NVARCHAR(20) NOT NULL DEFAULT 'Подтверждено',
    PaymentStatus NVARCHAR(20) NOT NULL DEFAULT 'Не оплачено',
    TotalAmount DECIMAL(10,2) NOT NULL,
    CreatedBy INT NOT NULL,
    CreatedDate DATETIME NOT NULL DEFAULT GETDATE(),
    ModifiedDate DATETIME NULL,
    FOREIGN KEY (RoomID) REFERENCES Rooms(RoomID),
    FOREIGN KEY (CreatedBy) REFERENCES Users(UserID)
);

-- Таблица заказов рум-сервиса
CREATE TABLE RoomServiceOrders (
    OrderID INT IDENTITY(1,1) PRIMARY KEY,
    BookingID INT NULL,
    RoomID INT NOT NULL,
    OrderDate DATETIME NOT NULL DEFAULT GETDATE(),
    ClientName NVARCHAR(100) NOT NULL,
    Status NVARCHAR(20) NOT NULL DEFAULT 'Не оплачен',
    TotalAmount DECIMAL(10,2) NOT NULL DEFAULT 0,
    Notes NVARCHAR(500) NULL,
    CreatedBy INT NOT NULL,
    FOREIGN KEY (BookingID) REFERENCES Bookings(BookingID),
    FOREIGN KEY (RoomID) REFERENCES Rooms(RoomID),
    FOREIGN KEY (CreatedBy) REFERENCES Users(UserID)
);

-- Таблица категорий меню
CREATE TABLE MenuCategories (
    CategoryID INT IDENTITY(1,1) PRIMARY KEY,
    CategoryName NVARCHAR(50) NOT NULL UNIQUE,
    Description NVARCHAR(200) NULL,
    ImagePath NVARCHAR(255) NULL
);

-- Таблица меню
CREATE TABLE MenuItems (
    ItemID INT IDENTITY(1,1) PRIMARY KEY,
    CategoryID INT NOT NULL,
    ItemName NVARCHAR(100) NOT NULL,
    Description NVARCHAR(500) NULL,
    Price DECIMAL(10,2) NOT NULL,
    IsAvailable BIT NOT NULL DEFAULT 1,
    ImagePath NVARCHAR(255) NULL,
    FOREIGN KEY (CategoryID) REFERENCES MenuCategories(CategoryID)
);

-- Таблица позиций в заказе рум-сервиса
CREATE TABLE RoomServiceOrderItems (
    OrderItemID INT IDENTITY(1,1) PRIMARY KEY,
    OrderID INT NOT NULL,
    ItemID INT NOT NULL,
    Quantity INT NOT NULL DEFAULT 1,
    UnitPrice DECIMAL(10,2) NOT NULL,
    Notes NVARCHAR(200) NULL,
    FOREIGN KEY (OrderID) REFERENCES RoomServiceOrders(OrderID),
    FOREIGN KEY (ItemID) REFERENCES MenuItems(ItemID)
);

-- Таблица истории статусов номеров
CREATE TABLE RoomStatusHistory (
    HistoryID INT IDENTITY(1,1) PRIMARY KEY,
    RoomID INT NOT NULL,
    Status NVARCHAR(20) NOT NULL,
    ChangedBy INT NOT NULL,
    ChangeDate DATETIME NOT NULL DEFAULT GETDATE(),
    Notes NVARCHAR(500) NULL,
    FOREIGN KEY (RoomID) REFERENCES Rooms(RoomID),
    FOREIGN KEY (ChangedBy) REFERENCES Users(UserID)
);

-- Таблица финансовых операций
CREATE TABLE FinancialTransactions (
    TransactionID INT IDENTITY(1,1) PRIMARY KEY,
    TransactionType NVARCHAR(50) NOT NULL,
    Amount DECIMAL(10,2) NOT NULL,
    BookingID INT NULL,
    OrderID INT NULL,
    Description NVARCHAR(200) NULL,
    CreatedBy INT NOT NULL,
    CreatedDate DATETIME NOT NULL DEFAULT GETDATE(),
    FOREIGN KEY (BookingID) REFERENCES Bookings(BookingID),
    FOREIGN KEY (OrderID) REFERENCES RoomServiceOrders(OrderID),
    FOREIGN KEY (CreatedBy) REFERENCES Users(UserID)
);