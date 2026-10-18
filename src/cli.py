def cli():
    should_exit = False
    while not should_exit:
        print("Welcome to the Mantis CLI. Please choose an option:")
        print("1. Analyze Logs")
        print("2. ChatBot")
        print("3. Exit")
        choice = input("Enter your choice: ")

        if choice == "1":
            from tools.log_analyzer import analyze_logs
            analyze_logs()
        elif choice == "2":
            print("ChatBot functionality is not implemented yet.")
        elif choice == "3":
            should_exit = True
        else:
            print("Invalid choice. Please try again.")
    