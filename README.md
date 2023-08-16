import tkinter as tk
from tkinter import messagebox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
import tempfile
import os
import win32print
import win32ui

class TaskManager:
    def __init__(self, root):
        self.root = root
        self.root.title("Gerenciador de Tarefas")

        self.load_tasks()

        self.task_input = tk.Entry(root)
        self.task_input.pack()

        self.add_button = tk.Button(root, text="Adicionar Tarefa", command=self.add_task)
        self.add_button.pack()

        self.delete_button = tk.Button(root, text="Excluir Tarefas Concluídas", command=self.delete_completed_tasks)
        self.delete_button.pack()

        self.frame = tk.Frame(root)
        self.frame.pack()

        self.counts_label = tk.Label(root, font=("Helvetica", 12))
        self.counts_label.pack()

        self.chart_frame = tk.Frame(root)
        self.chart_frame.pack()

        self.print_button = tk.Button(root, text="Imprimir Relatório", command=self.print_report)
        self.print_button.pack()

        self.export_pdf_button = tk.Button(root, text="Exportar PDF", command=self.export_pdf)
        self.export_pdf_button.pack()

        self.update_tasks()

    def load_tasks(self):
        try:
            with open("tasks.txt", "r") as file:
                self.tasks = eval(file.read())
        except FileNotFoundError:
            self.tasks = {"A Fazer": [], "Em Andamento": [], "Concluídas": []}

    def save_tasks(self):
        with open("tasks.txt", "w") as file:
            file.write(repr(self.tasks))

    def add_task(self):
        task_name = self.task_input.get()
        if task_name:
            self.tasks["A Fazer"].append({"nome": task_name, "prioridade": "Baixa"})
            self.save_tasks()
            self.update_tasks()
            self.task_input.delete(0, tk.END)

    def move_task(self, task, source_status, target_status):
        self.tasks[source_status].remove(task)
        self.tasks[target_status].append(task)
        self.save_tasks()
        self.update_tasks()

    def change_priority(self, task):
        if task["prioridade"] == "Baixa":
            task["prioridade"] = "Média"
        elif task["prioridade"] == "Média":
            task["prioridade"] = "Alta"
        else:
            task["prioridade"] = "Baixa"
        self.save_tasks()
        self.update_tasks()

    def delete_completed_tasks(self):
        self.tasks["Concluídas"] = []
        self.save_tasks()
        self.update_tasks()

    def generate_report(self):
        report = f"Relatório de Tarefas:\n\n"
        for status, tasks in self.tasks.items():
            report += f"{status}:\n"
            for task in tasks:
                report += f"- {task['nome']} (Prioridade: {task['prioridade']})\n"
            report += "\n"
        return report

    def print_report(self):
        report = self.generate_report()
        self.print_text(report)

    def print_text(self, text):
        printer_name = win32print.GetDefaultPrinter()
        hprinter = win32print.OpenPrinter(printer_name)
        printer_info = win32print.GetPrinter(hprinter, 2)
        device_mode = printer_info["pDevMode"]
        
        printer_handle = win32ui.CreateDC()
        printer_handle.CreatePrinterDC(printer_name)
        printer_handle.StartDoc('Print Report')
        printer_handle.StartPage()

        printer_handle.TextOut(100, 100, text)
        
        printer_handle.EndPage()
        printer_handle.EndDoc()
        printer_handle.DeleteDC()

    def save_pdf(self, text):
        pdf_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        doc = SimpleDocTemplate(pdf_file, pagesize=letter)
        styles = getSampleStyleSheet()
        story = [Table([[text]], style=TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.grey)]))]
        doc.build(story)
        pdf_file.close()
        return pdf_file.name

    def export_pdf(self):
        report = self.generate_report()
        pdf_path = self.save_pdf(report)
        os.startfile(pdf_path)

    def update_tasks(self):
        for widget in self.frame.winfo_children():
            widget.destroy()

        for status, tasks in self.tasks.items():
            status_label = tk.Label(self.frame, text=status, font=("Helvetica", 14, "bold"))
            status_label.pack(anchor=tk.W)
            for task in tasks:
                task_frame = tk.Frame(self.frame)
                task_label = tk.Label(task_frame, text="- " + task["nome"], anchor=tk.W)
                task_label.pack(side=tk.LEFT)
                if status == "A Fazer":
                    tk.Button(task_frame, text="Mover para Em Andamento",
                              command=lambda t=task: self.move_task(t, "A Fazer", "Em Andamento")).pack(side=tk.LEFT)
                elif status == "Em Andamento":
                    tk.Button(task_frame, text="Mover para Concluídas",
                              command=lambda t=task: self.move_task(t, "Em Andamento", "Concluídas")).pack(side=tk.LEFT)
                    tk.Button(task_frame, text="Alterar Prioridade",
                              command=lambda t=task: self.change_priority(t)).pack(side=tk.LEFT)
                    tk.Label(task_frame, text=f"P: {task['prioridade']}").pack(side=tk.RIGHT)
                task_frame.pack(anchor=tk.W)

        self.show_task_counts()
        self.show_task_chart()

    def show_task_counts(self):
        counts = [len(self.tasks["A Fazer"]), len(self.tasks["Em Andamento"]), len(self.tasks["Concluídas"])]
        counts_str = f"A Fazer: {counts[0]}, Em Andamento: {counts[1]}, Concluídas: {counts[2]}"
        self.counts_label.config(text=counts_str)

    def show_task_chart(self):
        self.chart_frame.destroy()
        self.chart_frame = tk.Frame(self.root)
        self.chart_frame.pack()

        counts = [len(self.tasks["A Fazer"]), len(self.tasks["Em Andamento"]), len(self.tasks["Concluídas"])]
        labels = ["A Fazer", "Em Andamento", "Concluídas"]

        fig, ax = plt.subplots()
        ax.bar(labels, counts)
        ax.set_xlabel("Status das Tarefas")
        ax.set_ylabel("Quantidade de Tarefas")
        ax.set_title("Contador de Tarefas")

        canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack()

if __name__ == "__main__":
    root = tk.Tk()
    app = TaskManager(root)
    root.mainloop()
